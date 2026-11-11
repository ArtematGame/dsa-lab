from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

ACCRUAL_RATE = Decimal("0.05")
REDEEM_LIMIT_RATE = Decimal("0.30")

# Статусы результата операции.
APPLIED = "applied"
REJECTED = "rejected"


# Доменная модель операции после преобразования JSON.
@dataclass(frozen=True)
class Operation:
    operation_id: str
    type: str
    customer_id: str
    store_id: str
    check_number: str
    amount: Decimal | None
    points: int | None
    occurred_at: datetime

    @classmethod
    def from_dict(cls, data):
        # Преобразование входных значений к типам доменной модели.
        amount = data.get("amount")
        return cls(
            operation_id=data["operation_id"],
            type=data["type"],
            customer_id=data["customer_id"],
            store_id=data["store_id"],
            check_number=data["check_number"],
            amount=Decimal(amount) if amount is not None else None,
            points=data.get("points"),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
        )


# Данные исходной покупки для проверки возврата.
@dataclass(frozen=True)
class Purchase:
    customer_id: str
    points: int


# Результат применения операции к балансу.
@dataclass(frozen=True)
class Result:
    status: str
    points_delta: int
    balance_after: int
    reject_reason: str | None


def accrual_points(amount):
    # Начисление 5 процентов с отбрасыванием дробной части.
    return int((amount * ACCRUAL_RATE).to_integral_value(rounding=ROUND_FLOOR))  # дробь отбрасывается


def applied(balance, delta):
    # Результат успешно применённой операции.
    return Result(APPLIED, delta, balance + delta, None)


def rejected(balance, reason):
    # Результат отклонённой операции без изменения баланса.
    return Result(REJECTED, 0, balance, reason)


def apply_operation(operation, balance, purchase, returned):
    # Проверка правил операции и вычисление изменения баланса.
    if operation.type == "purchase":
        if purchase is not None:
            return rejected(balance, "duplicate_purchase")
        return applied(balance, accrual_points(operation.amount))

    if operation.type == "return":
        if purchase is None:
            return rejected(balance, "purchase_not_found")
        if purchase.customer_id != operation.customer_id:
            return rejected(balance, "customer_mismatch")
        if returned:
            return rejected(balance, "already_returned")
        return applied(balance, -purchase.points)

    if operation.points > operation.amount * REDEEM_LIMIT_RATE:
        return rejected(balance, "limit_exceeded")
    if operation.points > balance:
        return rejected(balance, "insufficient_balance")
    return applied(balance, -operation.points)
