import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import aio_pika
from sqlalchemy.ext.asyncio import create_async_engine

import db
from domain import Operation, apply_operation

DATABASE_URL = os.environ["DATABASE_URL"]
RABBITMQ_URL = os.environ["RABBITMQ_URL"]

QUORUM = {"x-queue-type": "quorum"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def to_event(row):
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


async def process(engine, data):
    operation = Operation.from_dict(data)
    async with engine.begin() as conn:
        saved = await db.get_operation(conn, operation.operation_id)
        if saved is not None:  # повторная доставка
            return to_event(saved)
        balance = await db.lock_balance(conn, operation.customer_id)
        purchase = await db.find_purchase(conn, operation.check_number)
        returned = await db.is_returned(conn, operation.check_number)
        result = apply_operation(operation, balance, purchase, returned)
        await db.save_result(conn, operation, result, datetime.now(timezone.utc))
        saved = await db.get_operation(conn, operation.operation_id)
    return to_event(saved)


async def declare(channel):
    loyalty = await channel.declare_exchange("loyalty", aio_pika.ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue("operations", durable=True, arguments=QUORUM)
    await queue.bind(loyalty, routing_key="operation")
    events = await channel.declare_exchange(
        "loyalty.events", aio_pika.ExchangeType.FANOUT, durable=True
    )
    for name in ("notifier.events", "analytics.events"):
        subscriber = await channel.declare_queue(name, durable=True, arguments=QUORUM)
        await subscriber.bind(events, routing_key="")
    return queue, events


async def publish_event(events, event):
    message = aio_pika.Message(
        body=json.dumps(event).encode("utf-8"),
        content_type="application/json",
        message_id=event["operation_id"],
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    await events.publish(message, routing_key="", mandatory=True)


async def main():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(db.metadata.create_all)
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        await channel.set_qos(prefetch_count=1)
        queue, events = await declare(channel)
        log.info("waiting for operations")
        async with queue.iterator() as messages:
            async for message in messages:
                async with message.process(requeue=True):  # ack при выходе
                    event = await process(engine, json.loads(message.body.decode("utf-8")))
                    await publish_event(events, event)
                    log.info("%s %s %s %+d balance=%d", event["operation_id"], event["type"],
                             event["status"], event["points_delta"], event["balance_after"])
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
