from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit.logger import audit
from app.auth.jwt import make_token, verify_password
from app.db.models import Tenant, User
from app.deps import CurrentUser, get_current_user, get_db_unscoped

router = APIRouter()


class LoginIn(BaseModel):
    email: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, db: Session = Depends(get_db_unscoped)):
    """Login flow across tenants.

    Because `users` is under FORCE ROW LEVEL SECURITY we can't do a
    cross-tenant email query directly. Instead we iterate the (unprotected)
    tenants table and probe each tenant's user set with app.tenant_id set,
    so RLS lets us see exactly that tenant's rows.
    """
    tenants = db.execute(select(Tenant)).scalars().all()
    for t in tenants:
        db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.id)})
        u = db.execute(
            select(User).where(User.tenant_id == t.id, User.email == payload.email)
        ).scalar_one_or_none()
        if u and verify_password(payload.password, u.password_hash):
            token = make_token(
                user_id=str(u.id), tenant_id=str(u.tenant_id), email=u.email, role=u.role
            )
            audit(
                db,
                tenant_id=u.tenant_id,
                user_id=u.id,
                action="login",
                resource_type="user",
                resource_id=str(u.id),
            )
            return LoginOut(access_token=token, role=u.role)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")


class MeOut(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    role: str


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser = Depends(get_current_user)):
    return MeOut(user_id=user.user_id, tenant_id=user.tenant_id, email=user.email, role=user.role)
