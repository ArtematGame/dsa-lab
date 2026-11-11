import asyncio
import os
from contextlib import asynccontextmanager

import aio_pika
from aio_pika.exceptions import AMQPError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from schemas import OperationIn
from tables import accounts, operations

DATABASE_URL = os.environ["DATABASE_URL"]
RABBITMQ_URL = os.environ["RABBITMQ_URL"]
PUBLISH_TIMEOUT_S = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Подключение к базе данных и настройка очереди операций в RabbitMQ.
    app.state.engine = create_async_engine(DATABASE_URL)
    app.state.connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await app.state.connection.channel(publisher_confirms=True, on_return_raises=True)
    app.state.exchange = await channel.declare_exchange(
        "loyalty", aio_pika.ExchangeType.DIRECT, durable=True
    )
    queue = await channel.declare_queue(
        "operations", durable=True, arguments={"x-queue-type": "quorum"}
    )
    await queue.bind(app.state.exchange, routing_key="operation")
    app.state.channel = channel
    yield
    await app.state.connection.close()
    await app.state.engine.dispose()


app = FastAPI(lifespan=lifespan)


def to_result(row):
    # Преобразование строки базы данных в JSON-совместимый ответ.
    return {
        "operation_id": row["operation_id"],
        "type": row["type"],
        "customer_id": row["customer_id"],
        "store_id": row["store_id"],
        "status": row["status"],
        "points_delta": row["points_delta"],
        "balance_after": row["balance_after"],
        "reject_reason": row["reject_reason"],
        "processed_at": row["processed_at"].isoformat(),
    }


@app.post("/operations", status_code=202)
async def create_operation(operation: OperationIn, request: Request):
    # Публикация проверенной операции в очередь для асинхронной обработки.
    message = aio_pika.Message(
        body=operation.model_dump_json(exclude_none=True).encode("utf-8"),
        content_type="application/json",
        message_id=operation.operation_id,
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    try:
        await request.app.state.exchange.publish(
            message, routing_key="operation", mandatory=True, timeout=PUBLISH_TIMEOUT_S
        )  # ждём подтверждения
    except (AMQPError, asyncio.TimeoutError, ConnectionError, RuntimeError):
        raise HTTPException(status_code=503, detail="Брокер не подтвердил публикацию")
    return {"operation_id": operation.operation_id}


@app.get("/operations/{operation_id}")
async def get_operation(operation_id: str, request: Request):
    # Поиск результата обработки операции в базе данных.
    query = select(operations).where(operations.c.operation_id == operation_id)
    async with request.app.state.engine.connect() as conn:
        row = (await conn.execute(query)).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Операция ещё не обработана")
    return to_result(row)


@app.get("/accounts/{customer_id}")
async def get_account(customer_id: str, request: Request):
    # Баланс покупателя и список последних операций.
    async with request.app.state.engine.connect() as conn:
        balance = (await conn.execute(
            select(accounts.c.balance).where(accounts.c.customer_id == customer_id)
        )).scalar_one_or_none()
        if balance is None:
            raise HTTPException(status_code=404, detail="Счёт не найден")
        rows = (await conn.execute(
            select(operations)
            .where(operations.c.customer_id == customer_id)
            .order_by(operations.c.processed_at.desc())
            .limit(20)
        )).mappings().all()
    return {
        "customer_id": customer_id,
        "balance": balance,
        "operations": [to_result(row) for row in rows],
    }


@app.get("/health")
async def health(request: Request):
    # Проверка доступности базы данных и соединения с брокером.
    checks = {"database": "ok", "broker": "ok"}
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        checks["database"] = "unavailable"
    if request.app.state.connection.is_closed or request.app.state.channel.is_closed:
        checks["broker"] = "unavailable"
    status = 200 if all(value == "ok" for value in checks.values()) else 503
    return JSONResponse(checks, status_code=status)
