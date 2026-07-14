"""Critical: prove that tenant B cannot read tenant A's data at any layer.

Attacks tested:
  1. Direct SQL query as tenant B tries to SELECT tenant A's user row.
  2. INSERT into a tenant-scoped table with a foreign tenant_id.
  3. Qdrant search filtered by tenant B's id must not return tenant A's chunks
     (even if the raw chunk exists in the same shared collection).
"""

import uuid

import pytest
from qdrant_client.http import models as qm
from sqlalchemy import select, text

from app.config import settings
from app.db.models import User
from app.db.postgres import SessionLocal
from app.db.qdrant import client as qdrant, ensure_collection, tenant_filter


def _sess(tid):
    s = SessionLocal()
    s.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(tid)})
    return s


def test_rls_blocks_cross_tenant_select(two_tenants):
    a, b = two_tenants
    with _sess(b) as sb:
        # Session is scoped to B — trying to select A's users returns nothing.
        rows = sb.execute(select(User).where(User.tenant_id == uuid.UUID(a))).scalars().all()
        assert rows == [], "RLS leaked users across tenants!"


def test_rls_blocks_cross_tenant_insert(two_tenants):
    a, b = two_tenants
    # Session says we're tenant B; try to INSERT a row claiming tenant_id=A.
    with _sess(b) as sb:
        with pytest.raises(Exception):
            sb.add(
                User(
                    id=uuid.uuid4(),
                    tenant_id=uuid.UUID(a),  # cross-tenant write attempt
                    email="attacker@x.test",
                    password_hash="x",
                    role="user",
                )
            )
            sb.flush()
        sb.rollback()


def test_qdrant_filter_scopes_by_tenant(two_tenants):
    a, b = two_tenants
    ensure_collection()
    # Insert one point for each tenant with an obvious payload marker.
    dim = settings.vector_dim
    vec = [0.1] * dim
    pa, pb = str(uuid.uuid4()), str(uuid.uuid4())
    qdrant.upsert(
        settings.qdrant_collection,
        points=[
            qm.PointStruct(
                id=pa,
                vector=vec,
                payload={
                    "tenant_id": a, "parent_id": pa, "document_id": pa,
                    "component_type": "paragraph", "chunk_index": 0,
                    "suspected_injection": False, "text": "TENANT_A_SECRET",
                },
            ),
            qm.PointStruct(
                id=pb,
                vector=vec,
                payload={
                    "tenant_id": b, "parent_id": pb, "document_id": pb,
                    "component_type": "paragraph", "chunk_index": 0,
                    "suspected_injection": False, "text": "TENANT_B_SECRET",
                },
            ),
        ],
    )
    hits_b = qdrant.search(
        collection_name=settings.qdrant_collection,
        query_vector=vec,
        query_filter=tenant_filter(b),
        limit=10,
        with_payload=True,
    )
    assert all(h.payload["tenant_id"] == b for h in hits_b), "Qdrant filter leaked cross-tenant!"
    assert not any(h.payload["text"] == "TENANT_A_SECRET" for h in hits_b)
    qdrant.delete(settings.qdrant_collection, points_selector=qm.PointIdsList(points=[pa, pb]))
