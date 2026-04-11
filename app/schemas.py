from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class CheckoutRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, examples=[Decimal("500.00")])
    merchant_id: Optional[str] = Field(None, description="Website / merchant id when using API key")


class CheckoutResponse(BaseModel):
    order_id: str
    amount: str


class OrderResponse(BaseModel):
    order_id: str
    amount: str
    status: str
    utr_number: str | None = None
    merchant_id: str | None = None


class SmsWebhookBody(BaseModel):
    amount: Decimal
    utr: str = Field(..., min_length=1)
    merchant_id: Optional[str] = Field(
        None, description="If set, only match pending orders for this merchant"
    )


class SmsWebhookResponse(BaseModel):
    matched: bool
    order_id: str | None = None
    message: str


class UserBootstrapResponse(BaseModel):
    uid: str
    email: str | None
    role: str


class MerchantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    domain: str = Field(..., min_length=1, max_length=200)


class MerchantResponse(BaseModel):
    merchant_id: str
    name: str
    domain: str
    api_key: str
    created_at: str | None = None


class MerchantSummary(BaseModel):
    merchant_id: str
    name: str
    domain: str
    created_at: str | None = None


class StatsResponse(BaseModel):
    total_orders: int
    pending: int
    paid: int
    total_paid_amount: str


class AdminOrderRow(BaseModel):
    order_id: str
    amount: str
    status: str
    utr_number: str | None = None
    merchant_id: str | None = None
    created_at: str | None = None
