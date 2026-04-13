import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.cloud.firestore import SERVER_TIMESTAMP

from app.config import admin_uid_set, settings
from app.deps import get_current_user, is_admin_uid
from app.firebase_app import get_firestore
from app.schemas import (
    AdminOrderRow,
    AnalyticsDayRow,
    AnalyticsResponse,
    CheckoutRequest,
    CheckoutResponse,
    MerchantCreate,
    MerchantResponse,
    MerchantSummary,
    MerchantUpdate,
    OrderResponse,
    SmsWebhookBody,
    SmsWebhookResponse,
    StatsResponse,
    UserBootstrapResponse,
)

ORDERS = "orders"
MERCHANTS = "merchants"
USERS = "users"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="FlowPay API", version="2.0.0", lifespan=lifespan)

import logging
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import Request

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("uvicorn.error")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = await request.body()
    decoded = body.decode("utf-8", errors="replace")
    logger.error(f"[WEBHOOK 422 ERROR] Raw body received: {decoded}")
    logger.error(f"[WEBHOOK 422 ERROR] Validation details: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body_received": decoded},
    )


# ─── Health ─────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


# ─── Helpers ─────────────────────────────────────────────────────────


def _amount_key(d: Decimal) -> str:
    return f"{d.quantize(Decimal('0.01')):.2f}"


def _fmt_ts(ts) -> str | None:
    if ts is None:
        return None
    try:
        return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    except Exception:
        return None


def _resolve_merchant_from_api_key(db, api_key: str | None) -> tuple[Optional[str], Optional[dict]]:
    if not api_key or not api_key.strip():
        return None, None
    key = api_key.strip()
    q = db.collection(MERCHANTS).where("api_key", "==", key).limit(1)
    docs = list(q.stream())
    if not docs:
        raise HTTPException(status_code=401, detail="Invalid API key")
    doc = docs[0]
    return doc.id, doc.to_dict()


# ─── Auth ────────────────────────────────────────────────────────


@app.post("/api/auth/bootstrap", response_model=UserBootstrapResponse)
def auth_bootstrap(user: dict = Depends(get_current_user)):
    """Ensure user profile exists in Firestore (call after Firebase sign-in)."""
    db = get_firestore()
    uid = user["uid"]
    ref = db.collection(USERS).document(uid)
    snap = ref.get()
    email = user.get("email")
    admins = admin_uid_set()
    role = "admin" if is_admin_uid(uid, admins) else "merchant"
    if not snap.exists:
        ref.set(
            {
                "email": email,
                "role": role,
                "merchant_ids": [],
                "created_at": SERVER_TIMESTAMP,
            }
        )
    else:
        data = snap.to_dict() or {}
        if data.get("role") != role and role == "admin":
            ref.update({"role": "admin"})
    return UserBootstrapResponse(uid=uid, email=email, role=role)


@app.get("/api/me", response_model=UserBootstrapResponse)
def me(user: dict = Depends(get_current_user)):
    db = get_firestore()
    snap = db.collection(USERS).document(user["uid"]).get()
    role = "merchant"
    if snap.exists:
        role = (snap.to_dict() or {}).get("role") or "merchant"
    admins = admin_uid_set()
    if is_admin_uid(user["uid"], admins):
        role = "admin"
    return UserBootstrapResponse(uid=user["uid"], email=user.get("email"), role=role)


# ─── Merchants ────────────────────────────────────────────────────


@app.post("/api/merchants", response_model=MerchantResponse)
def create_merchant(body: MerchantCreate, user: dict = Depends(get_current_user)):
    db = get_firestore()
    mid = str(uuid.uuid4())
    api_key = "fp_live_" + secrets.token_urlsafe(32)
    db.collection(MERCHANTS).document(mid).set(
        {
            "name": body.name.strip(),
            "domain": body.domain.strip().lower(),
            "owner_uid": user["uid"],
            "api_key": api_key,
            "created_at": SERVER_TIMESTAMP,
        }
    )
    uref = db.collection(USERS).document(user["uid"])
    usnap = uref.get()
    mids = []
    if usnap.exists:
        mids = list((usnap.to_dict() or {}).get("merchant_ids") or [])
    if mid not in mids:
        mids.append(mid)
        uref.set({"merchant_ids": mids}, merge=True)
    return MerchantResponse(
        merchant_id=mid,
        name=body.name.strip(),
        domain=body.domain.strip().lower(),
        api_key=api_key,
        created_at=None,
    )


@app.patch("/api/merchants/{merchant_id}", response_model=MerchantResponse)
def update_merchant(merchant_id: str, body: MerchantUpdate, user: dict = Depends(get_current_user)):
    db = get_firestore()
    ref = db.collection(MERCHANTS).document(merchant_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Merchant not found")
    d = doc.to_dict() or {}
    if d.get("owner_uid") != user["uid"] and not is_admin_uid(user["uid"], admin_uid_set()):
        raise HTTPException(status_code=403, detail="Forbidden")
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.domain is not None:
        updates["domain"] = body.domain.strip().lower()
    if body.upi_id is not None:
        updates["upi_id"] = body.upi_id.strip()
    if body.upi_name is not None:
        updates["upi_name"] = body.upi_name.strip()
    if updates:
        ref.update(updates)
        d.update(updates)
    return MerchantResponse(
        merchant_id=merchant_id,
        name=str(d.get("name", "")),
        domain=str(d.get("domain", "")),
        api_key=str(d.get("api_key", "")),
        created_at=_fmt_ts(d.get("created_at")),
        upi_id=d.get("upi_id"),
        upi_name=d.get("upi_name"),
    )


@app.get("/api/merchants", response_model=list[MerchantSummary])
def list_merchants(user: dict = Depends(get_current_user)):
    db = get_firestore()
    if is_admin_uid(user["uid"], admin_uid_set()):
        out = []
        for doc in db.collection(MERCHANTS).stream():
            d = doc.to_dict() or {}
            out.append(
                MerchantSummary(
                    merchant_id=doc.id,
                    name=str(d.get("name", "")),
                    domain=str(d.get("domain", "")),
                    created_at=_fmt_ts(d.get("created_at")),
                )
            )
        return sorted(out, key=lambda x: x.merchant_id, reverse=True)
    usnap = db.collection(USERS).document(user["uid"]).get()
    mids = list((usnap.to_dict() or {}).get("merchant_ids") or []) if usnap.exists else []
    out = []
    for mid in mids:
        doc = db.collection(MERCHANTS).document(mid).get()
        if not doc.exists:
            continue
        d = doc.to_dict() or {}
        if d.get("owner_uid") != user["uid"]:
            continue
        out.append(
            MerchantSummary(
                merchant_id=doc.id,
                name=str(d.get("name", "")),
                domain=str(d.get("domain", "")),
                created_at=_fmt_ts(d.get("created_at")),
            )
        )
    return out


@app.get("/api/merchants/{merchant_id}/api-key")
def reveal_api_key(merchant_id: str, user: dict = Depends(get_current_user)):
    db = get_firestore()
    doc = db.collection(MERCHANTS).document(merchant_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Merchant not found")
    d = doc.to_dict() or {}
    if d.get("owner_uid") != user["uid"] and not is_admin_uid(user["uid"], admin_uid_set()):
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"api_key": d.get("api_key", "")}


@app.post("/api/merchants/{merchant_id}/rotate-key", response_model=MerchantResponse)
def rotate_api_key(merchant_id: str, user: dict = Depends(get_current_user)):
    db = get_firestore()
    ref = db.collection(MERCHANTS).document(merchant_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Merchant not found")
    d = doc.to_dict() or {}
    if d.get("owner_uid") != user["uid"] and not is_admin_uid(user["uid"], admin_uid_set()):
        raise HTTPException(status_code=403, detail="Forbidden")
    api_key = "fp_live_" + secrets.token_urlsafe(32)
    ref.update({"api_key": api_key})
    return MerchantResponse(
        merchant_id=merchant_id,
        name=str(d.get("name", "")),
        domain=str(d.get("domain", "")),
        api_key=api_key,
        created_at=_fmt_ts(d.get("created_at")),
    )


# ─── Orders helpers ───────────────────────────────────────────────


def _merchant_ids_visible(user: dict) -> Optional[list[str]]:
    """None means all merchants (platform admin)."""
    if is_admin_uid(user["uid"], admin_uid_set()):
        return None
    db = get_firestore()
    usnap = db.collection(USERS).document(user["uid"]).get()
    if not usnap.exists:
        return []
    return list((usnap.to_dict() or {}).get("merchant_ids") or [])


def _orders_for_user(db, user: dict, limit: int = 500):
    mids = _merchant_ids_visible(user)
    rows = []
    if mids is None:
        for doc in db.collection(ORDERS).limit(2000).stream():
            rows.append((doc.id, doc.to_dict() or {}))
        rows.sort(key=lambda x: str((x[1] or {}).get("created_at") or ""), reverse=True)
        rows = rows[:limit]
    else:
        if not mids:
            return []
        for mid in mids:
            for doc in db.collection(ORDERS).where("merchant_id", "==", mid).limit(500).stream():
                rows.append((doc.id, doc.to_dict() or {}))
        rows.sort(key=lambda x: str((x[1] or {}).get("created_at") or ""), reverse=True)
        rows = rows[:limit]
    return rows


# ─── Stats ──────────────────────────────────────────────────────


@app.get("/api/admin/stats", response_model=StatsResponse)
def admin_stats(user: dict = Depends(get_current_user)):
    db = get_firestore()
    rows = _orders_for_user(db, user, limit=2000)
    pending = paid = 0
    total_paid = Decimal("0")
    for _, data in rows:
        st = data.get("status", "Pending")
        if st == "Pending":
            pending += 1
        elif st == "Paid":
            paid += 1
            try:
                total_paid += Decimal(str(data.get("amount", "0")))
            except Exception:
                pass
    return StatsResponse(
        total_orders=len(rows),
        pending=pending,
        paid=paid,
        total_paid_amount=f"{total_paid.quantize(Decimal('0.01')):.2f}",
    )


# ─── Analytics ───────────────────────────────────────────────────


@app.get("/api/admin/analytics", response_model=AnalyticsResponse)
def admin_analytics(days: int = 7, user: dict = Depends(get_current_user)):
    if days not in (7, 30):
        days = 7
    db = get_firestore()
    rows = _orders_for_user(db, user, limit=2000)

    now = datetime.now(tz=timezone.utc)
    day_map: dict[str, dict] = {}
    for i in range(days):
        d = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        day_map[d] = {"orders": 0, "paid": 0, "revenue": Decimal("0")}

    total_revenue = Decimal("0")
    paid_count = 0

    for _, data in rows:
        ts = data.get("created_at")
        if ts is None:
            continue
        try:
            if hasattr(ts, "astimezone"):
                date_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
            else:
                date_str = str(ts)[:10]
        except Exception:
            continue
        if date_str not in day_map:
            continue
        day_map[date_str]["orders"] += 1
        st = data.get("status", "Pending")
        if st == "Paid":
            day_map[date_str]["paid"] += 1
            paid_count += 1
            try:
                amt = Decimal(str(data.get("amount", "0")))
                day_map[date_str]["revenue"] += amt
                total_revenue += amt
            except Exception:
                pass

    total_orders = len(rows)
    conv = f"{round((paid_count / total_orders) * 100)}%" if total_orders else "0%"
    avg_ov = (total_revenue / paid_count).quantize(Decimal("0.01")) if paid_count else Decimal("0")

    day_rows = [
        AnalyticsDayRow(
            date=d,
            orders=v["orders"],
            paid=v["paid"],
            revenue=f"{v['revenue'].quantize(Decimal('0.01')):.2f}",
        )
        for d, v in sorted(day_map.items())
    ]
    return AnalyticsResponse(
        days=day_rows,
        conversion_rate=conv,
        avg_order_value=f"{avg_ov:.2f}",
        total_revenue=f"{total_revenue.quantize(Decimal('0.01')):.2f}",
    )


# ─── Orders ──────────────────────────────────────────────────────


@app.get("/api/admin/orders", response_model=list[AdminOrderRow])
def admin_orders(user: dict = Depends(get_current_user)):
    db = get_firestore()
    rows = _orders_for_user(db, user, limit=500)
    out = []
    for oid, data in rows:
        out.append(
            AdminOrderRow(
                order_id=oid,
                amount=str(data.get("amount", "")),
                status=str(data.get("status", "Pending")),
                utr_number=data.get("utr_number"),
                merchant_id=data.get("merchant_id"),
                created_at=_fmt_ts(data.get("created_at")),
            )
        )
    return out


# ─── Checkout ────────────────────────────────────────────────────


@app.post("/api/checkout", response_model=CheckoutResponse)
def checkout(
    body: CheckoutRequest,
    x_api_key: str | None = Header(None, alias="X-API-Key"),
):
    db = get_firestore()
    merchant_id, _ = _resolve_merchant_from_api_key(db, x_api_key)
    if body.merchant_id:
        if not merchant_id:
            raise HTTPException(status_code=400, detail="X-API-Key required when merchant_id is sent")
        if merchant_id != body.merchant_id:
            raise HTTPException(status_code=403, detail="merchant_id does not match API key")
    order_id = str(uuid.uuid4())
    amount_str = _amount_key(body.amount)
    payload = {
        "amount": amount_str,
        "status": "Pending",
        "utr_number": None,
        "created_at": SERVER_TIMESTAMP,
    }
    if merchant_id:
        payload["merchant_id"] = merchant_id
    if body.customer_details:
        payload["customer_details"] = body.customer_details.model_dump()
    if body.shipping_address:
        payload["shipping_address"] = body.shipping_address.model_dump()
    if body.items:
        payload["items"] = [item.model_dump(mode="json") for item in body.items]
    if body.return_url:
        payload["return_url"] = body.return_url.strip()

    db.collection(ORDERS).document(order_id).set(payload)
    return CheckoutResponse(order_id=order_id, amount=amount_str, return_url=body.return_url)


@app.get("/api/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str):
    db = get_firestore()
    snap = db.collection(ORDERS).document(order_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Order not found")
    data = snap.to_dict() or {}
    utr = data.get("utr_number")
    return OrderResponse(
        order_id=order_id,
        amount=str(data.get("amount", "")),
        status=str(data.get("status", "Pending")),
        utr_number=str(utr) if utr is not None else None,
        merchant_id=data.get("merchant_id"),
        customer_details=data.get("customer_details"),
        shipping_address=data.get("shipping_address"),
        items=data.get("items"),
        return_url=data.get("return_url"),
    )


# ─── Webhook ─────────────────────────────────────────────────────


def verify_webhook_auth(authorization: str | None = Header(None)):
    expected = f"Bearer {settings.webhook_bearer_token}"
    if not authorization:
        logger2.error("[WEBHOOK AUTH] Missing Authorization header")
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if authorization != expected:
        logger2.error(f"[WEBHOOK AUTH] Token mismatch. Received: {authorization[:15]}... Expected: {expected[:15]}...")
        raise HTTPException(status_code=401, detail="Invalid Authorization")


from google.cloud.firestore_v1.base_query import FieldFilter

logger2 = logging.getLogger("uvicorn.error")


@app.post("/api/webhook/sms-sync", response_model=SmsWebhookResponse)
def sms_webhook(
    body: SmsWebhookBody,
    _auth: None = Depends(verify_webhook_auth),
):
    db = get_firestore()
    target = _amount_key(body.amount)
    logger2.info(f"[WEBHOOK] Received SMS Sync: amount={body.amount}, utr={body.utr}")

    col = db.collection(ORDERS)
    q = col.where(filter=FieldFilter("status", "==", "Pending"))
    for doc in q.stream():
        data = doc.to_dict() or {}
        if data.get("amount") != target:
            continue
        if body.merchant_id:
            if data.get("merchant_id") != body.merchant_id:
                continue
        doc.reference.update({"status": "Paid", "utr_number": body.utr.strip()})
        logger2.info(f"[WEBHOOK] SUCCESS: Order {doc.id} marked Paid for ₹{target}")
        return SmsWebhookResponse(matched=True, order_id=doc.id, message="Order marked paid")

    logger2.warning(f"[WEBHOOK] No pending order found for ₹{target}")
    return SmsWebhookResponse(matched=False, order_id=None, message="No pending order with this amount")
