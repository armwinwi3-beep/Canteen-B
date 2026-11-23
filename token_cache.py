"""Small in-memory cache of verified login tokens, so each request does not
re-verify with LINE / Supabase Auth. Tokens are stored only as SHA-256 hashes."""
import hashlib
import threading
import time


class TokenCache:
    def __init__(self, max_entries: int = 5000):
        self._entries: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()
        self._max = max_entries

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def get(self, token: str) -> dict | None:
        key = self._key(token)
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            if entry[0] <= time.time():
                del self._entries[key]
                return None
            return entry[1]

    def put(self, token: str, value: dict, expires_at: float) -> None:
        if expires_at <= time.time():
            return
        with self._lock:
            if len(self._entries) >= self._max:
                now = time.time()
                for key in [k for k, (exp, _) in self._entries.items() if exp <= now]:
                    del self._entries[key]
                if len(self._entries) >= self._max:
                    self._entries.clear()
            self._entries[self._key(token)] = (expires_at, value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
