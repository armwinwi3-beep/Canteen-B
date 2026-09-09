from fastapi import APIRouter, Depends, HTTPException, Response

from customer_auth import current_customer, customer_db

router = APIRouter(prefix="/customer", tags=["customer catalog"])


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
            .select("id,name,price,stock,is_tracking")
            .eq("merchant_id", store_id)
            .order("name")
            .execute().data or []
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Unable to load products") from None
    return {"store": store_rows[0], "products": products}
