import os
import unittest
from unittest.mock import MagicMock, patch

import line_notifications


class LineNotificationTests(unittest.TestCase):
    def test_missing_token_skips_notification(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(line_notifications, "staff_db") as db:
            self.assertFalse(line_notifications.notify_order_status({"customer_id": "c", "status": "cooking"}, "Fah"))
            db.assert_not_called()

    def test_pushes_status_to_order_customer(self):
        query = MagicMock()
        query.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"line_user_id": "U123"}]
        response = MagicMock()
        order = {"id": "o1", "customer_id": "c1", "order_code": "FAH-001", "status": "completed"}
        with patch.dict(os.environ, {"LINE_MESSAGING_CHANNEL_ACCESS_TOKEN": "token"}), patch.object(line_notifications, "staff_db", return_value=query), patch.object(line_notifications.httpx, "post", return_value=response) as post:
            self.assertTrue(line_notifications.notify_order_status(order, "Fah"))
        response.raise_for_status.assert_called_once()
        self.assertEqual(post.call_args.kwargs["json"]["to"], "U123")
        self.assertIn("อาหารเสร็จแล้ว", post.call_args.kwargs["json"]["messages"][0]["text"])


if __name__ == "__main__":
    unittest.main()
