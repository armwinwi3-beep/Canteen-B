import os
from datetime import datetime
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="Canteen API")

# --- โครงสร้างข้อมูลที่รับจากหน้าเว็บ ---
class OrderItem(BaseModel):
    product_id: str
    name: str
    qty: int
    price: float
    cost: float

class OrderRequest(BaseModel):
    merchant_id: str
    customer_name: str
    order_type: str
    items: List[OrderItem]

# --- API ---
@app.get("/")
def read_root():
    return {"message": "Welcome to Canteen API - ระบบหลังบ้านพร้อมใช้งาน!"}

@app.get("/products")
def get_products():
    response = supabase.table("products").select("*").execute()
    return {"status": "success", "data": response.data}

from datetime import datetime, timedelta, timezone

# ฟังก์ชันสำหรับแปลงเวลา UTC จากฐานข้อมูลเป็นเวลาไทย
def convert_to_thai_time(utc_time_str: str) -> str:
    # สมมติรูปแบบที่ได้จาก Supabase คือ '2026-08-27T14:18:26.116963+00:00'
    utc_time = datetime.fromisoformat(utc_time_str.replace('Z', '+00:00'))
    thai_timezone = timezone(timedelta(hours=7))
    thai_time = utc_time.astimezone(thai_timezone)
    return thai_time.strftime('%d/%m/%Y %H:%M:%S')

# ตัวอย่างการใช้งานตอนดึงข้อมูล
# thai_time_str = convert_to_thai_time(order_data['created_at'])
@app.post("/place-order")
def place_order(order: OrderRequest):
    try:
        # 1. สร้างรหัสออเดอร์
        timestamp_str = datetime.now().strftime('%Y%m%d%H%M%S')
        order_code = f"TOY-{timestamp_str}"
        total_price = sum(item.price * item.qty for item in order.items)

        # 2. บันทึกลงตาราง orders
        order_data = {
            "order_code": order_code,
            "merchant_id": order.merchant_id,
            "customer_name": order.customer_name,
            "order_type": order.order_type,
            "total_price": total_price,
            "status": "pending"
        }
        order_res = supabase.table("orders").insert(order_data).execute()
        new_order_id = order_res.data[0]['id']

        # 3. บันทึกรายการอาหาร และตัดสต็อก
        for item in order.items:
            # 3.1 บันทึกรายการอาหาร
            supabase.table("order_items").insert({
                "order_id": new_order_id,
                "product_id": item.product_id,
                "name": item.name,
                "qty": item.qty,
                "price": item.price,
                "cost": item.cost
            }).execute()

            # 3.2 ตรวจสอบและตัดสต็อก
            product_res = supabase.table("products").select("stock, is_tracking").eq("id", item.product_id).execute()
            if product_res.data:
                p_data = product_res.data[0]
                if p_data.get("is_tracking"):
                    new_stock = max(0, p_data["stock"] - item.qty)
                    
                    # อัปเดตสต็อก
                    supabase.table("products").update({"stock": new_stock}).eq("id", item.product_id).execute()
                    
                    # บันทึกประวัติ
                    supabase.table("stock_history").insert({
                        "product_name": item.name,
                        "action": "reduce",
                        "amount": item.qty,
                        "old_stock": p_data["stock"],
                        "new_stock": new_stock,
                        "old_cost": item.cost,
                        "new_cost": item.cost,
                        "detail": f"ขายผ่านระบบ (ออเดอร์: {order_code})"
                    }).execute()

        return {
            "status": "success", 
            "message": "สร้างออเดอร์และตัดสต็อกสำเร็จ!",
            "order_code": order_code
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}