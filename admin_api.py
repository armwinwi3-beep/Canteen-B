"""Admin API for creating and managing merchant stores."""
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from admin_auth import current_admin, current_staff, staff_db, staff_auth_client

router = APIRouter(prefix="/staff", tags=["staff"])
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=4096)


class CreateStoreRequest(BaseModel):
    store_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class StoreStatusRequest(BaseModel):
    is_open: bool


def _session_payload(auth_response) -> dict:
    session = auth_response.session
    if not session:
        raise HTTPException(401, "Incorrect email or password")
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_in": session.expires_in,
    }


@router.post("/login")
def login(body: LoginRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        result = staff_auth_client().auth.sign_in_with_password({
            "email": body.email.strip().lower(), "password": body.password,
        })
    except Exception:
        raise HTTPException(401, "Incorrect email or password") from None
    payload = _session_payload(result)
    # Authorization is checked immediately, before a token is returned to the web app.
    try:
        user_id = str(result.user.id)
        rows = staff_db().table("staff_accounts").select("role").eq("user_id", user_id).limit(1).execute().data or []
        allowed = bool(rows)
        if not allowed:
            raise HTTPException(403, "This account has no staff access")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Unable to check staff access") from None
    return payload


@router.post("/refresh")
def refresh(body: RefreshRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return _session_payload(staff_auth_client().auth.refresh_session(body.refresh_token))
    except Exception:
        raise HTTPException(401, "Staff session has expired") from None


@router.get("/me")
def me(response: Response, staff=Depends(current_staff)):
    response.headers["Cache-Control"] = "no-store"
    return {"staff": staff}


@router.get("/stores")
def stores(response: Response, _admin=Depends(current_admin)):
    response.headers["Cache-Control"] = "no-store"
    rows = staff_db().table("stores").select("id,name,is_open,created_at").order("created_at").execute().data or []
    accounts = staff_db().table("staff_accounts").select("email,store_id").eq("role", "merchant").execute().data or []
    emails = {row["store_id"]: row["email"] for row in accounts}
    return {"stores": [{**store, "email": emails.get(store["id"])} for store in rows]}


@router.post("/stores", status_code=201)
def create_store(body: CreateStoreRequest, _admin=Depends(current_admin)):
    name = body.store_name.strip()
    username = body.username.strip().lower()
    if not name:
        raise HTTPException(422, "Store name is required")
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(422, "Username must be 3-32 lowercase letters, numbers, dot, dash or underscore")
    if username == "admin":
        raise HTTPException(422, "This username is reserved")
    email = f"{username}@btadapp.com"
    try:
        created = staff_db().auth.admin.create_user({
            "email": email, "password": body.password, "email_confirm": True,
        }).user
    except Exception:
        raise HTTPException(409, "This username is already in use") from None
    store_id = str(created.id)
    try:
        store = staff_db().table("stores").insert({"id": store_id, "name": name, "is_open": True}).execute().data[0]
        staff_db().table("staff_accounts").insert({
            "user_id": store_id, "email": email, "role": "merchant", "store_id": store_id,
        }).execute()
    except Exception:
        try:
            staff_db().auth.admin.delete_user(store_id)
        finally:
            staff_db().table("stores").delete().eq("id", store_id).execute()
        raise HTTPException(503, "Unable to create store account") from None
    return {"store": {**store, "email": email}}


@router.patch("/stores/{store_id}")
def update_store_status(store_id: str, body: StoreStatusRequest, _admin=Depends(current_admin)):
    rows = staff_db().table("stores").update({"is_open": body.is_open}).eq("id", store_id).execute().data or []
    if not rows:
        raise HTTPException(404, "Store not found")
    return {"store": rows[0]}
