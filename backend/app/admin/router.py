import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from qdrant_client.http import models as qm
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.audit.logger import audit
from app.config import settings
from app.db.models import AuditLog, ChunkMeta, Document, FlaggedChunk
from app.db.qdrant import client as qdrant
from app.deps import CurrentUser, get_db, require_admin

router = APIRouter()

_SNIPPET_MAX = 600


class FlaggedOut(BaseModel):
    chunk_id: str
    filename: str
    chunk_index: int
    snippet: str  # the actual (masked) chunk text the classifier flagged
    reason: str | None
    status: str
    created_at: str


class DecisionIn(BaseModel):
    decision: str  # "approve" | "reject"
    notes: str | None = None


@router.get("/flagged", response_model=list[FlaggedOut])
def list_flagged(
    admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    rows = db.execute(
        select(FlaggedChunk, ChunkMeta, Document.filename)
        .join(ChunkMeta, ChunkMeta.id == FlaggedChunk.chunk_id)
        .join(Document, Document.id == ChunkMeta.document_id)
        .where(FlaggedChunk.status == "pending")
        .order_by(FlaggedChunk.created_at.desc())
    ).all()

    # The flagged chunk's exact text lives in the Qdrant payload; fetch it in
    # one batch. (IDs come from the RLS-scoped query above, so they are all
    # this tenant's chunks.) Fall back to empty if Qdrant is unreachable.
    texts: dict[str, str] = {}
    ids = [str(fc.chunk_id) for fc, _, _ in rows]
    if ids:
        try:
            points = qdrant.retrieve(settings.qdrant_collection, ids=ids, with_payload=True)
            texts = {str(p.id): (p.payload or {}).get("text", "") for p in points}
        except Exception:
            pass

    return [
        FlaggedOut(
            chunk_id=str(fc.chunk_id),
            filename=filename,
            chunk_index=cm.chunk_index,
            snippet=texts.get(str(fc.chunk_id), "")[:_SNIPPET_MAX],
            reason=fc.reason,
            status=fc.status,
            created_at=fc.created_at.isoformat(),
        )
        for fc, cm, filename in rows
    ]


@router.post("/flagged/{chunk_id}/decision", status_code=204)
def decide_flagged(
    chunk_id: uuid.UUID,
    body: DecisionIn,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if body.decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve|reject")
    fc = db.get(FlaggedChunk, chunk_id)
    if not fc:
        raise HTTPException(404, "not found")
    fc.status = "approved" if body.decision == "approve" else "rejected"
    fc.reviewed_by = uuid.UUID(admin.user_id)
    fc.reviewed_at = datetime.now(timezone.utc)
    fc.notes = body.notes
    # If approved, flip the chunk's suspected_injection so it becomes retrievable.
    if body.decision == "approve":
        cm = db.get(ChunkMeta, chunk_id)
        if cm:
            cm.suspected_injection = False
        qdrant.set_payload(
            settings.qdrant_collection,
            payload={"suspected_injection": False},
            points=[str(chunk_id)],
        )
    audit(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        action=f"flag_{body.decision}",
        resource_type="chunk",
        resource_id=str(chunk_id),
        meta={"notes": body.notes or ""},
    )
    return


class AuditOut(BaseModel):
    id: int
    action: str
    resource_type: str | None
    resource_id: str | None
    meta: dict
    created_at: str


@router.get("/audit", response_model=list[AuditOut])
def list_audit(
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    rows = db.execute(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)).scalars().all()
    return [
        AuditOut(
            id=r.id,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            meta=r.meta or {},
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
