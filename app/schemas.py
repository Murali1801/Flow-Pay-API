from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class CustomerDetails(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class ShippingAddress(BaseModel):
    full_name: str
    address_line_1: str
    address_line_2: Optional[str] = None
    city: str
    state: str
    pincode: str


class OrderItem(BaseModel):
    name: str
    quantity: int
    price: Decimal
    image: Optional[str] = None


class CheckoutRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, examples=[Decimal("500.00")])
    merchant_id: Optional[str] = Field(None, description="Website / merchant id when using API key")
    customer_details: Optional[CustomerDetails] = None
    shipping_address: Optional[ShippingAddress] = None
    items: Optional[list[OrderItem]] = None
    return_url: Optional[str] = Field(None, description="URL to redirect after payment (e.g. brochure /orders page)")


class CheckoutResponse(BaseModel):
    order_id: str
    amount: str
    return_url: Optional[str] = None


class OrderResponse(BaseModel):
    order_id: str
    amount: str
    status: str
    utr_number: str | None = None
    merchant_id: str | None = None
    customer_details: Optional[CustomerDetails] = None
    shipping_address: Optional[ShippingAddress] = None
    items: Optional[list[OrderItem]] = None
    return_url: Optional[str] = None


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


class MerchantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    domain: Optional[str] = Field(None, min_length=1, max_length=200)
    upi_id: Optional[str] = Field(None, max_length=100, description="UPI ID to receive payments")
    upi_name: Optional[str] = Field(None, max_length=100, description="Payee display name")


class MerchantResponse(BaseModel):
    merchant_id: str
    name: str
    domain: str
    api_key: str
    created_at: str | None = None
    upi_id: str | None = None
    upi_name: str | None = None


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


class AnalyticsDayRow(BaseModel):
    date: str
    orders: int
    paid: int
    revenue: str


class AnalyticsResponse(BaseModel):
    days: list[AnalyticsDayRow]
    conversion_rate: str
    avg_order_value: str
    total_revenue: str
