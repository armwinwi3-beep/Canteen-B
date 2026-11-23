import base64
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from customer_app import app
from admin_auth import verified_staff
from parallel import run_parallel


def jwt_with_exp(exp: float) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class StaffSessionCacheTests(unittest.TestCase):
    def setUp(self):
        verified_staff.clear()
        self.addCleanup(verified_staff.clear)
        self.client = TestClient(app)

    def call_me(self, token):
        return self.client.get('/staff/me', headers={'Authorization': f'Bearer {token}'})

    def mocked_db(self, factory):
        db = factory.return_value
        db.auth.get_user.return_value.user = SimpleNamespace(id='u1', email='lung@accounts.canteen.local')
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {'user_id': 'u1', 'username': 'lung', 'email': 'lung@accounts.canteen.local', 'role': 'merchant', 'store_id': 's1'}]
        return db

    def test_valid_session_is_verified_once_per_minute(self):
        token = jwt_with_exp(time.time() + 3600)
        with patch('admin_auth.staff_db') as factory:
            db = self.mocked_db(factory)
            for _ in range(3):
                self.assertEqual(self.call_me(token).json()['staff']['username'], 'lung')
            self.assertEqual(db.auth.get_user.call_count, 1)
            with patch('token_cache.time.time', return_value=time.time() + 61):
                self.call_me(token)
            self.assertEqual(db.auth.get_user.call_count, 2)

    def test_cache_never_outlives_token(self):
        token = jwt_with_exp(time.time() + 5)
        with patch('admin_auth.staff_db') as factory:
            db = self.mocked_db(factory)
            self.call_me(token)
            with patch('token_cache.time.time', return_value=time.time() + 6):
                self.call_me(token)
            self.assertEqual(db.auth.get_user.call_count, 2)

    def test_rejected_session_is_not_cached(self):
        token = jwt_with_exp(time.time() + 3600)
        with patch('admin_auth.staff_db') as factory:
            factory.return_value.auth.get_user.side_effect = RuntimeError('expired')
            self.assertEqual(self.call_me(token).status_code, 401)
        self.assertIsNone(verified_staff.get(token))


class ParallelTests(unittest.TestCase):
    def test_runs_concurrently_and_keeps_order(self):
        started = time.perf_counter()
        results = run_parallel(*[lambda n=n: (time.sleep(0.2), n)[1] for n in range(4)])
        self.assertEqual(results, [0, 1, 2, 3])
        self.assertLess(time.perf_counter() - started, 0.5)

    def test_errors_propagate(self):
        with self.assertRaises(ValueError):
            run_parallel(lambda: 1, lambda: (_ for _ in ()).throw(ValueError('boom')))


if __name__ == '__main__':
    unittest.main()
