"""Merchant-scoped menu and order management API."""
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from pydantic import BaseModel, Field

from admin_auth import current_staff, staff_db
from line_notifications import notify_order_status

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

class ExpenseCreate(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, decimal_places=2)
    expense_date: date


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
    products = staff_db().table("products").select("id,name,price,cost,stock,is_tracking,image_url,created_at").eq("merchant_id", store_id).order("created_at").execute().data or []
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
    stores = staff_db().table("stores").select("name").eq("id", account["store_id"]).limit(1).execute().data or []
    notify_order_status(rows[0], stores[0]["name"] if stores else "ร้านอาหาร")
    return {"order": rows[0]}

@router.post("/products/{product_id}/image")
async def upload_product_image(product_id: str, image: UploadFile = File(...), account=Depends(merchant)):
    allowed={"image/jpeg":"jpg","image/png":"png","image/webp":"webp"}
    if image.content_type not in allowed: raise HTTPException(422,"Use JPG, PNG or WebP")
    data=await image.read(5*1024*1024+1)
    if len(data)>5*1024*1024: raise HTTPException(413,"Image must be 5 MB or smaller")
    rows=staff_db().table("products").select("id").eq("id",product_id).eq("merchant_id",account["store_id"]).limit(1).execute().data or []
    if not rows: raise HTTPException(404,"Product not found")
    path=f"{account['store_id']}/{product_id}/{uuid4().hex}.{allowed[image.content_type]}"
    staff_db().storage.from_("product-images").upload(path,data,{"content-type":image.content_type,"upsert":"false"})
    url=staff_db().storage.from_("product-images").get_public_url(path)
    staff_db().table("products").update({"image_url":url}).eq("id",product_id).eq("merchant_id",account["store_id"]).execute()
    return {"image_url":url}

@router.post("/expenses", status_code=201)
def create_expense(body: ExpenseCreate, account=Depends(merchant)):
    row={"merchant_id":account["store_id"],"description":body.description.strip(),"amount":float(body.amount),"expense_date":body.expense_date.isoformat()}
    if not row["description"]: raise HTTPException(422,"Description is required")
    return {"expense":(staff_db().table("expenses").insert(row).execute().data or [row])[0]}

@router.get("/reports/daily")
def daily_report(day: date, response: Response, account=Depends(merchant)):
    no_cache(response); tz=timezone(timedelta(hours=7)); start=datetime.combine(day,time.min,tz).astimezone(timezone.utc); end=start+timedelta(days=1)
    orders=staff_db().table("orders").select("id,total_price").eq("merchant_id",account["store_id"]).eq("status","completed").gte("created_at",start.isoformat()).lt("created_at",end.isoformat()).execute().data or []
    ids=[o["id"] for o in orders]; items=[]
    if ids: items=staff_db().table("order_items").select("qty,cost").in_("order_id",ids).execute().data or []
    expenses=staff_db().table("expenses").select("id,description,amount,expense_date,created_at").eq("merchant_id",account["store_id"]).eq("expense_date",day.isoformat()).order("created_at",desc=True).execute().data or []
    revenue=sum(float(o["total_price"]) for o in orders); cost=sum(int(i["qty"])*float(i.get("cost") or 0) for i in items); expense=sum(float(e["amount"]) for e in expenses)
    return {"day":day,"revenue":revenue,"cost":cost,"expenses_total":expense,"net_income":revenue-cost-expense,"completed_orders":len(orders),"expenses":expenses}
