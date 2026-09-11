"""Send order status updates through the LINE Messaging API."""
import logging
import os

import httpx

from admin_auth import staff_db

logger = logging.getLogger(__name__)
STATUS_TEXT = {
    "pending": "ร้านได้รับคำสั่งซื้อแล้ว",
    "cooking": "ร้านกำลังทำอาหาร",
    "completed": "อาหารเสร็จแล้ว มารับได้เลย",
    "cancelled": "คำสั่งซื้อถูกยกเลิก",
}


def notify_order_status(order: dict, store_name: str) -> bool:
    token = os.getenv("LINE_MESSAGING_CHANNEL_ACCESS_TOKEN")
    customer_id = order.get("customer_id")
    status = str(order.get("status") or "")
    if not token or not customer_id or status not in STATUS_TEXT:
        return False
    customers = staff_db().table("line_customers").select("line_user_id").eq("id", customer_id).limit(1).execute().data or []
    if not customers:
        return False
    message = f"อัปเดตคำสั่งซื้อ {order['order_code']}\nร้าน {store_name}\nสถานะ: {STATUS_TEXT[status]}"
    try:
        response = httpx.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {token}"},
            json={"to": customers[0]["line_user_id"], "messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except (httpx.HTTPError, KeyError, TypeError):
        logger.exception("LINE order notification failed", extra={"order_id": order.get("id"), "status": status})
        return False
