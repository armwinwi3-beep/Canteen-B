import os
import time
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from customer_app import app
from customer_auth import verified_customers


class CustomerAuthTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"LINE_LOGIN_CHANNEL_ID": "123"})
        self.env.start()
        self.addCleanup(self.env.stop)
        verified_customers.clear()
        self.addCleanup(verified_customers.clear)
        self.client = TestClient(app)
        self.claims = {"iss": "https://access.line.me", "aud": "123", "sub": "Ualice",
                       "exp": time.time() + 600, "name": "Alice"}

    def request(self):
        return self.client.get('/auth/me', headers={"Authorization": "Bearer test-token"})

    def test_missing_token_never_calls_database(self):
        with patch('customer_auth.customer_db') as db:
            self.assertEqual(self.client.get('/auth/me').status_code, 401)
            db.assert_not_called()

    def test_wrong_audience_issuer_expiry_and_missing_subject_rejected(self):
        for key, value in [('aud', 'other'), ('iss', 'fake'), ('exp', 1), ('sub', '')]:
            with self.subTest(key=key), patch('customer_auth.httpx.post', return_value=Mock(status_code=200, json=lambda: {**self.claims, key: value})), patch('customer_auth.customer_db') as db:
                self.assertEqual(self.request().status_code, 401)
                db.assert_not_called()

    def test_line_rejection_and_outage(self):
        for status, expected in [(400, 401), (401, 401), (429, 503), (500, 503)]:
            with patch('customer_auth.httpx.post', return_value=Mock(status_code=status)):
                self.assertEqual(self.request().status_code, expected)
        with patch('customer_auth.httpx.post', side_effect=httpx.ConnectError('secret')):
            response = self.request()
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('secret', response.text)

    def test_verified_identity_stable_and_always_customer(self):
        with patch('customer_auth.httpx.post', return_value=Mock(status_code=200, json=lambda: self.claims)) as verify, patch('customer_auth.customer_db') as db:
            first = self.request()
            second = self.request()
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json(), second.json())
            self.assertEqual(first.json()['customer']['role'], 'customer')
            self.assertEqual(first.headers['cache-control'], 'no-store')
            self.assertEqual(verify.call_args.kwargs['data']['client_id'], '123')
            self.assertNotIn('line_user_id', first.json()['customer'])
            self.assertEqual(db.return_value.table.call_args.args, ('line_customers',))
            self.claims = {**self.claims, 'sub': 'Ubob'}
            bob = self.client.get('/auth/me', headers={"Authorization": "Bearer bob-token"})
            self.assertNotEqual(first.json()['customer']['id'], bob.json()['customer']['id'])

    def test_verified_token_is_reused_without_calling_line_again(self):
        with patch('customer_auth.httpx.post', return_value=Mock(status_code=200, json=lambda: self.claims)) as verify, patch('customer_auth.customer_db') as db:
            for _ in range(3):
                self.assertEqual(self.request().status_code, 200)
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(db.return_value.table.return_value.upsert.call_count, 1)

    def test_expired_cache_entry_verifies_again(self):
        with patch('customer_auth.httpx.post', return_value=Mock(status_code=200, json=lambda: self.claims)) as verify, patch('customer_auth.customer_db'):
            self.request()
            with patch('token_cache.time.time', return_value=time.time() + 601):
                self.request()
        self.assertEqual(verify.call_count, 2)

    def test_database_failure_does_not_leak_details(self):
        with patch('customer_auth.httpx.post', return_value=Mock(status_code=200, json=lambda: self.claims)), patch('customer_auth.customer_db', side_effect=RuntimeError('secret')):
            response = self.request()
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('secret', response.text)

    def test_legacy_order_route_not_exposed(self):
        self.assertEqual(self.client.post('/place-order', json={}).status_code, 404)

    def test_cors_only_allows_configured_origin(self):
        for origin, allowed in [('http://localhost:5173', True), ('https://attacker.example', False)]:
            response = self.client.options('/auth/me', headers={'Origin': origin, 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'authorization'})
            self.assertEqual('access-control-allow-origin' in response.headers, allowed)


if __name__ == '__main__':
    unittest.main()
