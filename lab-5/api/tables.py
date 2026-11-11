from sqlalchemy import Column, DateTime, Integer, MetaData, Numeric, String, Table

metadata = MetaData()

accounts = Table(
    "accounts",
    metadata,
    Column("customer_id", String, primary_key=True),
    Column("balance", Integer, nullable=False),
)

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
)
