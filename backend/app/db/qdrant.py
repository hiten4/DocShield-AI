"""Qdrant client + collection bootstrap.

Tenant isolation is enforced by a MUST payload filter on `tenant_id`
attached to every search. The `tenant_id` is resolved server-side from
the JWT and is never taken from client input.
"""

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import settings

client = QdrantClient(url=settings.qdrant_url)


def ensure_collection() -> None:
    collections = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection in collections:
        return
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=qm.VectorParams(size=settings.vector_dim, distance=qm.Distance.COSINE),
    )
    # Payload indexes for fast tenant filtering + injection exclusion
    client.create_payload_index(
        settings.qdrant_collection, field_name="tenant_id", field_schema=qm.PayloadSchemaType.KEYWORD
    )
    client.create_payload_index(
        settings.qdrant_collection,
        field_name="suspected_injection",
        field_schema=qm.PayloadSchemaType.BOOL,
    )
    client.create_payload_index(
        settings.qdrant_collection, field_name="document_id", field_schema=qm.PayloadSchemaType.KEYWORD
    )


def tenant_filter(tenant_id: str, exclude_flagged: bool = True) -> qm.Filter:
    must = [qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=tenant_id))]
    if exclude_flagged:
        must.append(qm.FieldCondition(key="suspected_injection", match=qm.MatchValue(value=False)))
    return qm.Filter(must=must)
