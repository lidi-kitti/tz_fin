from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_serializer

from app.models.enums import Currency, PaymentStatus


class PaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    currency: Currency
    description: str = Field(..., min_length=1, max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl


class PaymentCreatedResponse(BaseModel):
    payment_id: UUID
    status: PaymentStatus
    created_at: datetime


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None = None

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.01')):.2f}"


class PaymentEvent(BaseModel):
    payment_id: UUID
    attempt: int = 1
