"""FastAPI dependencies for auth + tenant-scoped DB session.

The critical invariant here: `tenant_id` is resolved from the verified JWT
server-side, then written to Postgres GUC `app.tenant_id`. Row-level
security policies use that GUC. The client cannot supply `tenant_id`.
"""

from dataclasses import dataclass
from typing import Iterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.jwt import decode_token
from app.db.postgres import SessionLocal


@dataclass
class CurrentUser:
    user_id: str
    tenant_id: str
    email: str
    role: str  # "user" | "admin"


def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        claims = decode_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    return CurrentUser(
        user_id=claims["sub"],
        tenant_id=claims["tid"],
        email=claims["email"],
        role=claims.get("role", "user"),
    )


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user


def get_db(user: CurrentUser = Depends(get_current_user)) -> Iterator[Session]:
    """Session with Postgres GUC set to the caller's tenant_id, enabling RLS."""
    session = SessionLocal()
    try:
        # set_config with is_local=true so it lives for this transaction
        session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": user.tenant_id},
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_unscoped() -> Iterator[Session]:
    """Session WITHOUT tenant scoping. Only for login/register — no tenant-scoped reads allowed."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
