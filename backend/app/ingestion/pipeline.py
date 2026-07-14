"""Ingestion orchestrator.

Executed inside an RQ worker. Steps mirror the finalized design:

  raw bytes -> AV scan -> sandboxed parse -> sanitize -> PII mask
    -> refine component -> chunk (type-specific) -> per-chunk injection scan
    -> embed (batched) -> store (Postgres parents + Qdrant child vectors)

Failures set the document status to `failed` or `quarantined` and log
to audit. Flagged chunks are stored with `suspected_injection=true` and
routed to the admin review queue — never silently deleted.
"""

import logging
import uuid

from qdrant_client.http import models as qm
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ChunkMeta, Document, FlaggedChunk, Parent
from app.db.postgres import SessionLocal
from app.db.qdrant import client as qdrant, ensure_collection
from app.ingestion.av_scan import scan_bytes
from app.ingestion.chunker import chunk_block
from app.ingestion.classifier import refine_component
from app.ingestion.embedder import embed_batch
from app.ingestion.injection_scan import classify as inj_classify
from app.ingestion.pii_mask import mask_text
from app.ingestion.pii_vault import write_mapping as vault_write
from app.ingestion.sandbox import SandboxError, parse_in_sandbox
from app.ingestion.sanitize import sanitize_text

log = logging.getLogger(__name__)


def _db_for_tenant(tenant_id: str) -> Session:
    s = SessionLocal()
    s.execute(sql_text("SELECT set_config('app.tenant_id', :t, false)"), {"t": tenant_id})
    return s


def process_document(document_id: str, tenant_id: str, content_type: str, data: bytes) -> None:
    ensure_collection()
    db = _db_for_tenant(tenant_id)
    try:
        doc = db.get(Document, uuid.UUID(document_id))
        if not doc:
            log.error("document %s missing", document_id)
            return
        doc.status = "processing"
        db.flush()

        # 1. AV scan.
        clean, sig = scan_bytes(data)
        if not clean:
            doc.status = "quarantined"
            doc.error = f"antivirus: {sig}"
            db.commit()
            return

        # 2. Sandboxed parse (returns typed Blocks).
        try:
            blocks = parse_in_sandbox(content_type, data)
        except SandboxError as e:
            doc.status = "failed"
            doc.error = f"parse: {e}"
            db.commit()
            return

        # 3-4. Sanitize + PII mask each block's text (parent side). Every
        # mask token gets persisted to the encrypted per-tenant vault so the
        # query path can unmask the LLM's answer for legitimate callers.
        prepared = []
        doc_mapping: dict[str, tuple[str, str]] = {}
        for b in blocks:
            b.text = sanitize_text(b.text)
            b = refine_component(b)
            masked_text, mapping = mask_text(b.text)
            b.text = masked_text
            doc_mapping.update(mapping)
            prepared.append(b)

        if doc_mapping:
            vault_write(db, tenant_id, document_id, doc_mapping)
            db.flush()

        # 5. Chunk (type-specific).
        all_children = []
        parents_to_insert: list[Parent] = []
        for b in prepared:
            parent_id, children = chunk_block(b)
            parents_to_insert.append(
                Parent(
                    id=uuid.UUID(parent_id),
                    tenant_id=uuid.UUID(tenant_id),
                    document_id=doc.id,
                    component_type=b.kind,
                    content=b.text,
                    page_no=b.page_no,
                    section_path=b.section_path,
                )
            )
            all_children.extend(children)

        if not all_children:
            doc.status = "processed"
            db.commit()
            return

        # 6. Per-chunk injection classify.
        flags: list[tuple[bool, float, str]] = [inj_classify(c.text) for c in all_children]

        # 7. Embed only safe children (flagged ones still get stored, but excluded from retrieval).
        vectors = embed_batch([c.text for c in all_children])

        # 8. Persist. Order matters because of FK constraints:
        #    parents -> chunks_meta -> flagged_chunks
        # Explicit flushes force the correct insertion order regardless of
        # SQLAlchemy's unit-of-work topology decisions.
        db.add_all(parents_to_insert)
        db.flush()

        chunks_meta_rows = []
        flagged_rows = []
        points = []
        for c, (is_inj, score, reason), vec in zip(all_children, flags, vectors):
            cid = uuid.uuid4()
            chunks_meta_rows.append(
                ChunkMeta(
                    id=cid,
                    tenant_id=uuid.UUID(tenant_id),
                    parent_id=uuid.UUID(c.parent_id),
                    document_id=doc.id,
                    chunk_index=c.chunk_index,
                    suspected_injection=is_inj,
                    flag_reason=reason if is_inj else None,
                )
            )
            if is_inj:
                flagged_rows.append(
                    FlaggedChunk(
                        chunk_id=cid,
                        tenant_id=uuid.UUID(tenant_id),
                        reason=reason,
                    )
                )
            points.append(
                qm.PointStruct(
                    id=str(cid),
                    vector=vec,
                    payload={
                        "tenant_id": tenant_id,
                        "parent_id": c.parent_id,
                        "document_id": str(doc.id),
                        "component_type": c.component_type,
                        "chunk_index": c.chunk_index,
                        "suspected_injection": bool(is_inj),
                        "text": c.text,
                    },
                )
            )
        db.add_all(chunks_meta_rows)
        db.flush()
        if flagged_rows:
            db.add_all(flagged_rows)
            db.flush()

        # Batch upsert into Qdrant.
        for i in range(0, len(points), 256):
            qdrant.upsert(settings.qdrant_collection, points=points[i : i + 256])

        doc.status = "processed"
        db.commit()
        log.info(
            "processed doc=%s parents=%d chunks=%d flagged=%d",
            document_id,
            len(parents_to_insert),
            len(all_children),
            sum(1 for f in flags if f[0]),
        )
    except Exception as e:
        log.exception("ingestion failed for %s: %s", document_id, e)
        # Roll back first: if the failure was a DB error the session is in a
        # failed-transaction state and db.get() would raise, leaving the
        # document stuck in "processing" forever.
        db.rollback()
        try:
            doc = db.get(Document, uuid.UUID(document_id))
            if doc:
                doc.status = "failed"
                doc.error = str(e)[:1000]
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
