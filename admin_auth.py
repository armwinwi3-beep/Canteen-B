"""Authentication and authorization for admin and merchant web users."""
import os
from functools import lru_cache

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import create_client

bearer = HTTPBearer(auto_error=False)


@lru_cache
def staff_db():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise HTTPException(503, "Staff database is not configured")
    return create_client(url, key)


def staff_auth_client():
    # Never sign users into the cached service-role database client.
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])


def current_staff(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Staff access token is required")
    try:
        auth_user = staff_db().auth.get_user(credentials.credentials).user
    except Exception:
        raise HTTPException(401, "Staff session has expired") from None
    if not auth_user or not auth_user.email:
        raise HTTPException(401, "Invalid staff account")

    rows = (
        staff_db().table("staff_accounts")
        .select("user_id,email,role,store_id")
        .eq("user_id", str(auth_user.id)).limit(1).execute().data or []
    )
    if rows:
        return rows[0]

    raise HTTPException(403, "This account has no staff access")


def current_admin(staff: dict = Depends(current_staff)) -> dict:
    if staff["role"] != "admin":
        raise HTTPException(403, "Admin access is required")
    return staff
