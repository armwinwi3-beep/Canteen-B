import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from fastapi.testclient import TestClient
from customer_app import app


class StaffSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_anonymous_cannot_manage_stores(self):
        for method, path, body in [('get', '/staff/stores', None), ('post', '/staff/stores', {}), ('patch', '/staff/stores/a', {'is_open': True})]:
            kwargs = {'json': body} if body is not None else {}
            self.assertEqual(getattr(self.client, method)(path, **kwargs).status_code, 401)

    def test_email_alone_never_grants_admin(self):
        with patch('admin_auth.staff_db') as factory:
            db = factory.return_value
            db.auth.get_user.return_value.user = SimpleNamespace(id='test', email='admin@btadapp.com')
            db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
            result = self.client.get('/staff/stores', headers={'Authorization': 'Bearer test'})
            self.assertEqual(result.status_code, 403)
            db.table.return_value.insert.assert_not_called()

    def test_merchant_cannot_manage_stores(self):
        from admin_auth import current_staff
        app.dependency_overrides[current_staff] = lambda: {'role': 'merchant'}
        try:
            self.assertEqual(self.client.get('/staff/stores').status_code, 403)
        finally:
            app.dependency_overrides.clear()

    def test_login_never_mutates_database_auth_session(self):
        with patch('admin_api.staff_auth_client') as auth, patch('admin_api.staff_db') as database:
            auth.return_value.auth.sign_in_with_password.return_value = SimpleNamespace(
                user=SimpleNamespace(id='admin'), session=SimpleNamespace(access_token='access', refresh_token='refresh', expires_in=3600))
            database.return_value.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = [
                SimpleNamespace(data=[{'email': 'admin@btadapp.com'}]),
                SimpleNamespace(data=[{'role': 'admin'}]),
            ]
            result = self.client.post('/staff/login', json={'username':'admin','password':'test-password'})
            self.assertEqual(result.status_code, 200)
            database.return_value.auth.sign_in_with_password.assert_not_called()

    def test_admin_cannot_use_merchant_dashboard(self):
        from admin_auth import current_staff
        app.dependency_overrides[current_staff] = lambda: {'role': 'admin', 'store_id': None}
        try:
            self.assertEqual(self.client.get('/merchant/dashboard').status_code, 403)
        finally:
            app.dependency_overrides.clear()

    def test_product_payload_rejects_negative_values(self):
        from admin_auth import current_staff
        app.dependency_overrides[current_staff] = lambda: {'role': 'merchant', 'store_id': 'store-a'}
        try:
            response = self.client.post('/merchant/products', json={
                'name': 'ข้าว', 'price': -1, 'cost': 0, 'stock': -1, 'is_tracking': True,
            })
            self.assertEqual(response.status_code, 422)
        finally:
            app.dependency_overrides.clear()

if __name__ == '__main__':
    unittest.main()
