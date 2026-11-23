import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from customer_app import app
from customer_auth import current_customer
from admin_auth import current_staff

STORE = {"id": "store-a", "name": "Fah Kitchen", "is_open": True}
CUSTOMER = {"id": "c1", "display_name": "Ann", "picture_url": None, "role": "customer"}
MERCHANT = {"role": "merchant", "store_id": "store-a"}


def db_with_store(rpc_result=None, rpc_error=None):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [STORE]
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [STORE]
    call = db.rpc.return_value.execute
    if rpc_error:
        call.side_effect = APIError({"message": rpc_error[0], "code": rpc_error[1]})
    else:
        call.return_value = SimpleNamespace(data=rpc_result)
    return db


class CustomerOrderTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_customer] = lambda: CUSTOMER
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def post(self, db, items=None):
        with patch("catalog.customer_db", return_value=db), patch("catalog.notify_order_status") as notify:
            response = self.client.post("/customer/orders", json={"store_id": "store-a", "items": items or [{"product_id": "p1", "qty": 2}]})
        return response, notify

    def test_order_is_placed_in_one_rpc_call(self):
        db = db_with_store({"id": "o1", "order_code": "FAH-001", "total_price": "90.00", "status": "pending"})
        response, notify = self.post(db, [{"product_id": "p1", "qty": 1}, {"product_id": "p1", "qty": 2}])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["order"], {"id": "o1", "order_code": "FAH-001", "total_price": 90.0, "status": "pending"})
        name, params = db.rpc.call_args.args
        self.assertEqual(name, "place_order")
        self.assertEqual(params["p_prefix"], "FAH")
        self.assertEqual(params["p_order_type"], "online")
        self.assertEqual(params["p_customer_id"], "c1")
        # Duplicate lines are sent as-is; the SQL function merges them.
        self.assertEqual(len(params["p_items"]), 2)
        db.table.return_value.insert.assert_not_called()
        db.table.return_value.update.assert_not_called()
        notify.assert_called_once()

    def test_database_errors_map_to_http_errors(self):
        cases = [
            (("insufficient_stock:ข้าวมันไก่", "P0001"), 409, "ข้าวมันไก่ has insufficient stock"),
            (("product_unavailable", "P0001"), 422, "Some products are unavailable"),
            (("invalid input syntax for type uuid", "22P02"), 422, "Some products are unavailable"),
            (("store_closed", "P0001"), 409, "Store is closed"),
            (("deadlock detected", "40P01"), 503, "Unable to place order"),
        ]
        for error, status, detail in cases:
            with self.subTest(error=error):
                response, notify = self.post(db_with_store(rpc_error=error))
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["detail"], detail)
                notify.assert_not_called()


class MerchantOrderTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_staff] = lambda: MERCHANT
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def patch_status(self, db, status="cancelled"):
        with patch("merchant_api.staff_db", return_value=db), patch("merchant_api.notify_order_status") as notify:
            response = self.client.patch("/merchant/orders/o1", json={"status": status})
        return response, notify

    def test_status_change_uses_locked_rpc_and_notifies(self):
        order = {"id": "o1", "order_code": "FAH-001", "status": "cancelled", "customer_id": "c1"}
        db = db_with_store({"changed": True, "order": order})
        response, notify = self.patch_status(db)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.rpc.call_args.args, ("set_order_status", {"p_order_id": "o1", "p_merchant_id": "store-a", "p_status": "cancelled"}))
        db.table.return_value.update.assert_not_called()
        notify.assert_called_once_with(order, "Fah Kitchen")

    def test_unchanged_status_sends_no_line_message(self):
        db = db_with_store({"changed": False, "order": {"id": "o1", "status": "cooking"}})
        response, notify = self.patch_status(db, "cooking")
        self.assertEqual(response.status_code, 200)
        notify.assert_not_called()

    def test_cancelled_order_cannot_change_again(self):
        response, notify = self.patch_status(db_with_store(rpc_error=("order_cancelled", "P0001")), "pending")
        self.assertEqual(response.status_code, 409)
        notify.assert_not_called()

    def test_unknown_order_is_not_found(self):
        response, _ = self.patch_status(db_with_store(rpc_error=("order_not_found", "P0001")))
        self.assertEqual(response.status_code, 404)

    def test_walk_in_order_uses_rpc(self):
        db = db_with_store({"id": "o2", "order_code": "FAH-002", "total_price": 45, "status": "pending"})
        with patch("merchant_api.staff_db", return_value=db):
            response = self.client.post("/merchant/walk-in-orders", json={"items": [{"product_id": "p1", "qty": 1}]})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["order"]["tracking_path"], "/track/o2")
        params = db.rpc.call_args.args[1]
        self.assertEqual((params["p_order_type"], params["p_customer_id"], params["p_customer_name"]), ("walk_in", None, "ลูกค้าหน้าร้าน"))


if __name__ == "__main__":
    unittest.main()
