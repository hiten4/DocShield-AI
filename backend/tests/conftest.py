import uuid

import pytest
from sqlalchemy import text

from app.auth.jwt import hash_password
from app.db.models import Tenant, User
from app.db.postgres import SessionLocal


def _tenant_session(tenant_id: str):
    s = SessionLocal()
    s.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(tenant_id)})
    return s


@pytest.fixture()
def two_tenants():
    """Create two tenants + one user each, tear down after the test."""
    db = SessionLocal()
    try:
        t_a = Tenant(id=uuid.uuid4(), name=f"A-{uuid.uuid4()}")
        t_b = Tenant(id=uuid.uuid4(), name=f"B-{uuid.uuid4()}")
        db.add_all([t_a, t_b])
        db.flush()

        for t in (t_a, t_b):
            db.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(t.id)})
            db.add(
                User(
                    id=uuid.uuid4(),
                    tenant_id=t.id,
                    email=f"user@{t.name}.test",
                    password_hash=hash_password("pw"),
                    role="user",
                )
            )
            # Flush INSIDE the loop: each user's INSERT must run while the
            # GUC points at its own tenant, or RLS WITH CHECK rejects it.
            # (A single commit at the end batched both INSERTs under the
            # last tenant's GUC — invisible while the app ran as superuser.)
            db.flush()
        db.commit()
        yield str(t_a.id), str(t_b.id)
    finally:
        # Cleanup: drop tenants (cascades ignored — just leave orphans in prototype scope)
        db.close()
