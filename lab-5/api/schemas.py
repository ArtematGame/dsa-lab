from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class OperationIn(BaseModel):
    operation_id: str = Field(min_length=1)
    type: Literal["purchase", "return", "redeem"]
    customer_id: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    check_number: str = Field(min_length=1)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    points: int | None = Field(default=None, gt=0, strict=True)
    occurred_at: datetime

    @model_validator(mode="after")
    def check_fields(self):
        if self.type == "return":
            if self.amount is not None:
                raise ValueError("amount must be absent for return")
        elif self.amount is None:
            raise ValueError("amount is required for purchase and redeem")
        if self.type == "redeem":
            if self.points is None:
                raise ValueError("points is required for redeem")
        elif self.points is not None:
            raise ValueError("points must be absent for purchase and return")
        return self
