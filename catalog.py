from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from uuid import UUID

from customer_auth import current_customer, customer_db
from line_notifications import notify_order_status
from parallel import run_parallel

router = APIRouter(prefix="/customer", tags=["customer catalog"])

class CartItem(BaseModel):
    product_id: str
    qty: int = Field(ge=1, le=99)

class OrderCreate(BaseModel):
    store_id: str
    items: list[CartItem] = Field(min_length=1, max_length=50)


def _no_store_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def order_code_prefix(store: dict) -> str:
    return "".join(char for char in str(store.get("name") or "") if char.isalnum())[:3].upper() or "Q"


def _rpc_failure(exc: Exception) -> tuple[str, str]:
    return str(getattr(exc, "message", "") or ""), str(getattr(exc, "code", "") or "")


def place_order(db, store: dict, order_type: str, items, customer_id: str | None, customer_name: str) -> dict:
    """Create the order, its items, stock changes and queue number in one DB transaction."""
    try:
        result = db.rpc("place_order", {
            "p_merchant_id": store["id"],
            "p_prefix": order_code_prefix(store),
            "p_order_type": order_type,
            "p_customer_id": customer_id,
            "p_customer_name": customer_name,
            "p_items": [{"product_id": item.product_id, "qty": item.qty} for item in items],
        }).execute()
    except Exception as exc:
        message, code = _rpc_failure(exc)
        if message == "store_closed":
            raise HTTPException(409, "Store is closed") from None
        if message == "product_unavailable" or code == "22P02":
            raise HTTPException(422, "Some products are unavailable") from None
        if message.startswith("insufficient_stock:"):
            raise HTTPException(409, f"{message.split(':', 1)[1]} has insufficient stock") from None
        raise HTTPException(503, "Unable to place order") from None
    if not isinstance(result.data, dict) or not result.data.get("id"):
        raise HTTPException(503, "Unable to place order")
    return result.data


@router.get("/stores")
def list_stores(response: Response, _customer=Depends(current_customer)):
    _no_store_cache(response)
    db = customer_db()
    try:
        stores, pending = run_parallel(
            lambda: db.table("stores").select("id,name,is_open").eq("is_open", True).order("name").execute().data or [],
            lambda: db.table("orders").select("merchant_id").eq("status", "pending").execute().data or [],
        )
    except Exception:
        raise HTTPException(503, "Unable to load stores") from None
    queue_counts: dict[str, int] = {}
    for row in pending:
        merchant_id = str(row.get("merchant_id", ""))
        queue_counts[merchant_id] = queue_counts.get(merchant_id, 0) + 1
    return {"stores": [{**store, "queue_count": queue_counts.get(str(store["id"]), 0)} for store in stores]}


@router.get("/stores/{store_id}/products")
def list_products(store_id: str, response: Response, _customer=Depends(current_customer)):
    _no_store_cache(response)
    if len(store_id) > 100:
        raise HTTPException(404, "Store not found")
    db = customer_db()
    try:
        store_rows, products = run_parallel(
            lambda: db.table("stores").select("id,name,is_open").eq("id", store_id).eq("is_open", True).limit(1).execute().data or [],
            lambda: db.table("products").select("id,name,price,stock,is_tracking,image_url").eq("merchant_id", store_id).order("name").execute().data or [],
        )
    except Exception:
        raise HTTPException(503, "Unable to load products") from None
    if not store_rows:
        raise HTTPException(404, "Store not found")
    return {"store": store_rows[0], "products": products}


@router.get("/orders")
def list_customer_orders(response: Response, customer=Depends(current_customer)):
    _no_store_cache(response)
    db = customer_db()
    try:
        orders = (
            db.table("orders")
            .select("id,order_code,merchant_id,total_price,status,created_at")
            .eq("customer_id", customer["id"])
            .order("created_at", desc=True)
            .limit(50)
            .execute().data or []
        )
        order_ids = [order["id"] for order in orders]
        merchant_ids = list({order["merchant_id"] for order in orders})
        items, stores = run_parallel(
            lambda: (db.table("order_items").select("id,order_id,name,qty,price").in_("order_id", order_ids).execute().data or []) if order_ids else [],
            lambda: (db.table("stores").select("id,name").in_("id", merchant_ids).execute().data or []) if merchant_ids else [],
        )
    except Exception:
        raise HTTPException(503, "Unable to load orders") from None
    items_by_order: dict[str, list] = {}
    for item in items:
        items_by_order.setdefault(str(item["order_id"]), []).append(item)
    store_names = {str(store["id"]): store["name"] for store in stores}
    return {"orders": [{**order, "store_name": store_names.get(str(order["merchant_id"]), "ร้านอาหาร"), "items": items_by_order.get(str(order["id"]), [])} for order in orders]}


@router.get("/public/orders/{order_id}")
def public_order_tracking(order_id: UUID, response: Response):
    _no_store_cache(response)
    db = customer_db()
    orders = db.table("orders").select("id,order_code,merchant_id,total_price,status,created_at").eq("id", str(order_id)).limit(1).execute().data or []
    if not orders:
        raise HTTPException(404, "Order not found")
    order = orders[0]
    stores, items, active = run_parallel(
        lambda: db.table("stores").select("name").eq("id", order["merchant_id"]).limit(1).execute().data or [],
        lambda: db.table("order_items").select("id,name,qty,price").eq("order_id", str(order_id)).execute().data or [],
        lambda: db.table("orders").select("id,status,created_at").eq("merchant_id", order["merchant_id"]).in_("status", ["pending", "cooking"]).order("created_at").execute().data or [],
    )
    active_ids = [str(item["id"]) for item in active]
    position = active_ids.index(str(order_id)) + 1 if str(order_id) in active_ids else None
    return {"order":{**order,"store_name":stores[0]["name"] if stores else "ร้านอาหาร","items":items,"position":position,"queue_ahead":position-1 if position else 0,"active_queue":len(active)}}

@router.post("/orders", status_code=201)
def create_order(body: OrderCreate, background: BackgroundTasks, customer=Depends(current_customer)):
    db = customer_db()
    stores = db.table("stores").select("id,name,is_open").eq("id", body.store_id).eq("is_open", True).limit(1).execute().data or []
    if not stores: raise HTTPException(409, "Store is closed")
    created = place_order(db, stores[0], "online", body.items, customer["id"], customer["display_name"])
    order = {
        "id": created["id"],
        "order_code": created["order_code"],
        "customer_id": customer["id"],
        "total_price": float(created["total_price"]),
        "status": created["status"],
    }
    # The LINE push is sent after the response, so the customer is not kept waiting.
    background.add_task(notify_order_status, order, stores[0]["name"])
    return {"order": {key: value for key, value in order.items() if key != "customer_id"}}
