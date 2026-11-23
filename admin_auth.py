"""Authentication and authorization for admin and merchant web users."""
import base64
import json
import os
import time
from functools import lru_cache

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import create_client

from parallel import pooled_client_options
from token_cache import TokenCache

bearer = HTTPBearer(auto_error=False)
verified_staff = TokenCache()


@lru_cache
def staff_db():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise HTTPException(503, "Staff database is not configured")
    return create_client(url, key, options=pooled_client_options())


def _token_expiry(token: str) -> float:
    """Read `exp` from an already-verified JWT; used only to cap the cache lifetime."""
    try:
        payload = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"])
    except Exception:
        return 0.0


def staff_auth_client():
    # Never sign users into the cached service-role database client.
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])


def current_staff(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Staff access token is required")
    # Reuse a verified staff session for up to 60 s (never past token expiry)
    # instead of two Supabase round trips on every dashboard refresh.
    cached = verified_staff.get(credentials.credentials)
    if cached:
        return dict(cached)
    try:
        auth_user = staff_db().auth.get_user(credentials.credentials).user
    except Exception:
        raise HTTPException(401, "Staff session has expired") from None
    if not auth_user or not auth_user.email:
        raise HTTPException(401, "Invalid staff account")

    rows = (
        staff_db().table("staff_accounts")
        .select("user_id,username,email,role,store_id")
        .eq("user_id", str(auth_user.id)).limit(1).execute().data or []
    )
    if rows:
        verified_staff.put(credentials.credentials, rows[0], min(_token_expiry(credentials.credentials), time.time() + 60))
        return dict(rows[0])

    raise HTTPException(403, "This account has no staff access")


def current_admin(staff: dict = Depends(current_staff)) -> dict:
    if staff["role"] != "admin":
        raise HTTPException(403, "Admin access is required")
    return staff
