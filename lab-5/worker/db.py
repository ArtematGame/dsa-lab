from sqlalchemy import (Column, DateTime, Index, Integer, MetaData, Numeric, String,
                        Table, select, update)
from sqlalchemy.dialects.postgresql import insert

from domain import APPLIED, Purchase

# Структура таблиц и запросы для worker.
metadata = MetaData()

# Таблица текущих балансов покупателей.
accounts = Table(
    "accounts",
    metadata,
    Column("customer_id", String, primary_key=True),
    Column("balance", Integer, nullable=False),
)

# Таблица операций и индексы для поиска по покупателю и чеку.
operations = Table(
    "operations",
    metadata,
    Column("operation_id", String, primary_key=True),
    Column("type", String, nullable=False),
    Column("customer_id", String, nullable=False),
    Column("store_id", String, nullable=False),
    Column("check_number", String, nullable=False),
    Column("amount", Numeric(12, 2)),
    Column("points_delta", Integer, nullable=False),
    Column("balance_after", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("reject_reason", String),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=False),
    Index("operations_customer_idx", "customer_id", "processed_at"),
    Index("operations_check_idx", "check_number", "type"),
)


async def get_operation(conn, operation_id):
    # Проверка, была ли операция обработана ранее.
    query = select(operations).where(operations.c.operation_id == operation_id)
    return (await conn.execute(query)).mappings().first()


async def lock_balance(conn, customer_id):
    # Создание счёта при необходимости и его блокировка на время транзакции.
    await conn.execute(
        insert(accounts)
        .values(customer_id=customer_id, balance=0)
        .on_conflict_do_nothing()  # первая операция
    )
    query = select(accounts.c.balance).where(accounts.c.customer_id == customer_id).with_for_update()
    return (await conn.execute(query)).scalar_one()


async def find_applied(conn, operation_type, check_number):
    # Поиск применённой операции по типу и номеру чека.
    query = select(operations.c.customer_id, operations.c.points_delta).where(
        operations.c.type == operation_type,
        operations.c.check_number == check_number,
        operations.c.status == APPLIED,
    )
    return (await conn.execute(query)).first()


async def find_purchase(conn, check_number):
    # Данные покупки, на которую ссылается возврат.
    row = await find_applied(conn, "purchase", check_number)
    return Purchase(row.customer_id, row.points_delta) if row else None


async def is_returned(conn, check_number):
    # Проверка наличия возврата по этому чеку.
    return await find_applied(conn, "return", check_number) is not None


async def save_result(conn, operation, result, processed_at):
    # Сохранение результата операции и нового баланса в одной транзакции.
    await conn.execute(
        operations.insert().values(
            operation_id=operation.operation_id,
            type=operation.type,
            customer_id=operation.customer_id,
            store_id=operation.store_id,
            check_number=operation.check_number,
            amount=operation.amount,
            points_delta=result.points_delta,
            balance_after=result.balance_after,
            status=result.status,
            reject_reason=result.reject_reason,
            occurred_at=operation.occurred_at,
            processed_at=processed_at,
        )
    )
    await conn.execute(
        update(accounts)
        .where(accounts.c.customer_id == operation.customer_id)
        .values(balance=result.balance_after)
    )
