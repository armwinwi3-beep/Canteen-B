"""Customer identity from LINE. LINE tokens are never Supabase sessions."""
import os
import time
from functools import lru_cache
from uuid import UUID, uuid5

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import create_client

router = APIRouter(prefix="/auth", tags=["customer auth"])
bearer = HTTPBearer(auto_error=False)
IDENTITY_NAMESPACE = UUID("8759f361-ef24-4f78-bfd9-8a00ca5d1669")


@lru_cache
def customer_db():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise HTTPException(503, "Customer database is not configured")
    return create_client(url, key)


def verify_line_token(token: str) -> dict:
    channel = os.getenv("LINE_LOGIN_CHANNEL_ID")
    if not channel:
        raise HTTPException(503, "LINE login is not configured")
    try:
        result = httpx.post(
            "https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": token, "client_id": channel}, timeout=10,
        )
    except httpx.RequestError:
        raise HTTPException(503, "LINE verification is unavailable") from None
    if result.status_code in (400, 401):
        raise HTTPException(401, "Please reopen LIFF and sign in again")
    if result.status_code != 200:
        raise HTTPException(503, "LINE verification is unavailable")
    try:
        claims = result.json()
        valid = (
            claims.get("iss") == "https://access.line.me"
            and claims.get("aud") == channel
            and isinstance(claims.get("sub"), str)
            and bool(claims["sub"])
            and float(claims["exp"]) > time.time()
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        valid = False
    if not valid:
        raise HTTPException(401, "Invalid LINE identity")
    return claims


def current_customer(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "LINE ID token is required")
    if len(credentials.credentials) > 16384:
        raise HTTPException(401, "Invalid LINE token")
    claims = verify_line_token(credentials.credentials)
    # Stable across repeated/concurrent logins; frontend cannot choose identity or role.
    customer = {
        "id": str(uuid5(IDENTITY_NAMESPACE, claims["aud"] + ":" + claims["sub"])),
        "line_channel_id": claims["aud"],
        "line_user_id": claims["sub"],
        "display_name": claims.get("name") or "ลูกค้า LINE",
        "picture_url": claims.get("picture"),
    }
    try:
        customer_db().table("line_customers").upsert(customer, on_conflict="id").execute()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Unable to save customer account") from None
    return {"id": customer["id"], "display_name": customer["display_name"],
            "picture_url": customer["picture_url"], "role": "customer"}


@router.get("/me")
def me(response: Response, customer=Depends(current_customer)):
    response.headers["Cache-Control"] = "no-store"
    return {"customer": customer}
