from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from uuid import uuid4

from customer_auth import current_customer, customer_db

router = APIRouter(prefix="/customer", tags=["customer catalog"])

class CartItem(BaseModel):
    product_id: str
    qty: int = Field(ge=1, le=99)

class OrderCreate(BaseModel):
    store_id: str
    items: list[CartItem] = Field(min_length=1, max_length=50)


def _no_store_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/stores")
def list_stores(response: Response, _customer=Depends(current_customer)):
    _no_store_cache(response)
    try:
        stores = (
            customer_db().table("stores")
            .select("id,name,is_open")
            .eq("is_open", True)
            .order("name")
            .execute().data or []
        )
        pending = customer_db().table("orders").select("merchant_id").eq("status", "pending").execute().data or []
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
    try:
        store_rows = customer_db().table("stores").select("id,name,is_open").eq("id", store_id).eq("is_open", True).limit(1).execute().data or []
        if not store_rows:
            raise HTTPException(404, "Store not found")
        products = (
            customer_db().table("products")
            .select("id,name,price,stock,is_tracking,image_url")
            .eq("merchant_id", store_id)
            .order("name")
            .execute().data or []
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Unable to load products") from None
    return {"store": store_rows[0], "products": products}

@router.post("/orders", status_code=201)
def create_order(body: OrderCreate, customer=Depends(current_customer)):
    db = customer_db()
    stores = db.table("stores").select("id,name,is_open").eq("id", body.store_id).eq("is_open", True).limit(1).execute().data or []
    if not stores: raise HTTPException(409, "Store is closed")
    quantities = {item.product_id: item.qty for item in body.items}
    rows = db.table("products").select("id,name,price,cost,stock,is_tracking").eq("merchant_id", body.store_id).in_("id", list(quantities)).execute().data or []
    if len(rows) != len(quantities): raise HTTPException(422, "Some products are unavailable")
    total = 0.0
    for product in rows:
        qty = quantities[str(product["id"])]
        if product["is_tracking"] and product["stock"] < qty: raise HTTPException(409, f"{product['name']} has insufficient stock")
        total += float(product["price"]) * qty
    order_id, code = str(uuid4()), f"WEB-{uuid4().hex[:8].upper()}"
    try:
        db.table("orders").insert({"id":order_id,"order_code":code,"merchant_id":body.store_id,"customer_id":customer["id"],"customer_name":customer["display_name"],"order_type":"online","total_price":total,"status":"pending"}).execute()
        db.table("order_items").insert([{"order_id":order_id,"product_id":p["id"],"name":p["name"],"qty":quantities[str(p["id"])],"price":float(p["price"]),"cost":float(p.get("cost") or 0)} for p in rows]).execute()
        for p in rows:
            if p["is_tracking"]: db.table("products").update({"stock":p["stock"]-quantities[str(p["id"])]}).eq("id",p["id"]).eq("merchant_id",body.store_id).execute()
    except Exception:
        db.table("order_items").delete().eq("order_id", order_id).execute(); db.table("orders").delete().eq("id", order_id).execute()
        raise HTTPException(503, "Unable to place order") from None
    return {"order":{"id":order_id,"order_code":code,"total_price":total,"status":"pending"}}
