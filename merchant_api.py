"""Merchant-scoped menu and order management API."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from admin_auth import current_staff, staff_db

router = APIRouter(prefix="/merchant", tags=["merchant"])
ORDER_STATUSES = {"pending", "cooking", "completed", "cancelled"}


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(ge=0, decimal_places=2)
    cost: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    stock: int = Field(default=0, ge=0)
    is_tracking: bool = False


class ProductUpdate(ProductCreate):
    pass


class OrderStatusUpdate(BaseModel):
    status: str


def merchant(staff: dict = Depends(current_staff)) -> dict:
    if staff.get("role") != "merchant" or not staff.get("store_id"):
        raise HTTPException(403, "Merchant access is required")
    return staff


def no_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/dashboard")
def dashboard(response: Response, account=Depends(merchant)):
    no_cache(response)
    store_id = account["store_id"]
    stores = staff_db().table("stores").select("id,name,is_open").eq("id", store_id).limit(1).execute().data or []
    if not stores:
        raise HTTPException(404, "Store not found")
    products = staff_db().table("products").select("id,name,price,cost,stock,is_tracking,created_at").eq("merchant_id", store_id).order("created_at").execute().data or []
    orders = staff_db().table("orders").select("id,order_code,customer_name,order_type,total_price,status,created_at").eq("merchant_id", store_id).order("created_at", desc=True).limit(100).execute().data or []
    order_ids = [row["id"] for row in orders]
    items = []
    if order_ids:
        items = staff_db().table("order_items").select("id,order_id,product_id,name,qty,price,cost").in_("order_id", order_ids).execute().data or []
    by_order: dict[str, list] = {}
    for item in items:
        by_order.setdefault(str(item.get("order_id")), []).append(item)
    return {
        "account": account,
        "store": stores[0],
        "products": products,
        "orders": [{**order, "items": by_order.get(str(order["id"]), [])} for order in orders],
    }


@router.post("/products", status_code=201)
def create_product(body: ProductCreate, account=Depends(merchant)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Product name is required")
    row = {
        "name": name,
        "price": float(body.price),
        "cost": float(body.cost),
        "stock": body.stock,
        "is_tracking": body.is_tracking,
        "merchant_id": account["store_id"],
    }
    created = staff_db().table("products").insert(row).execute().data or []
    if not created:
        raise HTTPException(503, "Unable to create product")
    return {"product": created[0]}


@router.put("/products/{product_id}")
def update_product(product_id: str, body: ProductUpdate, account=Depends(merchant)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Product name is required")
    changes = {"name": name, "price": float(body.price), "cost": float(body.cost), "stock": body.stock, "is_tracking": body.is_tracking}
    rows = staff_db().table("products").update(changes).eq("id", product_id).eq("merchant_id", account["store_id"]).execute().data or []
    if not rows:
        raise HTTPException(404, "Product not found")
    return {"product": rows[0]}


@router.patch("/orders/{order_id}")
def update_order_status(order_id: str, body: OrderStatusUpdate, account=Depends(merchant)):
    if body.status not in ORDER_STATUSES:
        raise HTTPException(422, "Invalid order status")
    rows = staff_db().table("orders").update({"status": body.status}).eq("id", order_id).eq("merchant_id", account["store_id"]).execute().data or []
    if not rows:
        raise HTTPException(404, "Order not found")
    return {"order": rows[0]}
