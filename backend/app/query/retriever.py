from dataclasses import dataclass

from app.config import settings
from app.db.qdrant import client as qdrant, tenant_filter
from app.ingestion.embedder import embed_query


@dataclass
class Candidate:
    chunk_id: str
    parent_id: str
    document_id: str
    text: str
    component_type: str
    score: float


def search(tenant_id: str, question: str, top_k: int | None = None) -> list[Candidate]:
    vec = embed_query(question)
    hits = qdrant.search(
        collection_name=settings.qdrant_collection,
        query_vector=vec,
        query_filter=tenant_filter(tenant_id, exclude_flagged=True),
        limit=top_k or settings.top_k_vector,
        with_payload=True,
    )
    return [
        Candidate(
            chunk_id=str(h.id),
            parent_id=h.payload["parent_id"],
            document_id=h.payload["document_id"],
            text=h.payload["text"],
            component_type=h.payload["component_type"],
            score=h.score,
        )
        for h in hits
    ]
