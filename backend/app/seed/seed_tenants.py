"""Seed two demo tenants + admin/user accounts. Run: `python -m app.seed.seed_tenants`.

Because RLS is FORCED on user-scoped tables, we set `app.tenant_id`
for each tenant's session before inserting its users.
"""

import uuid

from sqlalchemy import select, text

from app.auth.jwt import hash_password
from app.db.models import Tenant, User
from app.db.postgres import SessionLocal


def _set_tenant(db, tid):
    db.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(tid)})


def _upsert_tenant(db, name):
    existing = db.execute(select(Tenant).where(Tenant.name == name)).scalar_one_or_none()
    if existing:
        return existing
    t = Tenant(id=uuid.uuid4(), name=name)
    db.add(t)
    db.flush()
    return t


def _upsert_user(db, tenant_id, email, password, role):
    _set_tenant(db, tenant_id)
    existing = db.execute(
        select(User).where(User.tenant_id == tenant_id, User.email == email)
    ).scalar_one_or_none()
    if existing:
        return existing
    u = User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email=email,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(u)
    db.flush()
    return u


def main():
    db = SessionLocal()
    try:
        acme = _upsert_tenant(db, "Acme Corp")
        globex = _upsert_tenant(db, "Globex")
        db.commit()

        _upsert_user(db, acme.id, "admin@acme.test", "acme-admin-pw", "admin")
        _upsert_user(db, acme.id, "user@acme.test", "acme-user-pw", "user")
        db.commit()

        _upsert_user(db, globex.id, "admin@globex.test", "globex-admin-pw", "admin")
        _upsert_user(db, globex.id, "user@globex.test", "globex-user-pw", "user")
        db.commit()

        print("Seeded tenants + users:")
        print("  Acme  admin: admin@acme.test / acme-admin-pw")
        print("  Acme  user:  user@acme.test  / acme-user-pw")
        print("  Globex admin: admin@globex.test / globex-admin-pw")
        print("  Globex user:  user@globex.test  / globex-user-pw")
    finally:
        db.close()


if __name__ == "__main__":
    main()
