import hashlib
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from redis import Redis
from rq import Queue
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit.logger import audit
from app.config import settings
from app.db.models import ChunkMeta, Document, FlaggedChunk, PiiVault
from app.db.qdrant import client as qdrant, tenant_filter
from app.deps import CurrentUser, get_current_user, get_db
from qdrant_client.http import models as qm

router = APIRouter()

_ACCEPTED = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt",
}

_redis = Redis.from_url(settings.redis_url)
_queue = Queue("ingestion", connection=_redis)


class DocumentOut(BaseModel):
    id: str
    filename: str
    status: str
    created_at: str


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in _ACCEPTED:
        raise HTTPException(400, f"unsupported content type: {file.content_type}")
    data = await file.read()
    if len(data) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(413, "file too large")
    sha = hashlib.sha256(data).hexdigest()

    doc = Document(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(user.tenant_id),
        filename=file.filename or "unknown",
        content_type=file.content_type,
        sha256=sha,
        uploaded_by=uuid.UUID(user.user_id),
        status="pending",
    )
    db.add(doc)
    audit(db, tenant_id=user.tenant_id, user_id=user.user_id, action="upload",
          resource_type="document", resource_id=str(doc.id),
          meta={"filename": file.filename, "size": len(data), "sha256": sha})
    # Commit FIRST so the worker can see the row. Otherwise there's a race
    # between "enqueue" (visible to worker via Redis) and the request-scope
    # commit that happens after the response returns.
    db.commit()

    _queue.enqueue(
        "app.workers.tasks.ingest_task",
        str(doc.id),
        str(user.tenant_id),
        file.content_type,
        data,
        job_timeout=1800,  # 30 min — first-run model downloads can be slow
    )
    return {"document_id": str(doc.id), "status": "pending"}


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    rows = db.execute(select(Document).order_by(Document.created_at.desc())).scalars().all()
    return [
        DocumentOut(id=str(r.id), filename=r.filename, status=r.status, created_at=r.created_at.isoformat())
        for r in rows
    ]


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: uuid.UUID, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "not found")
    return DocumentOut(id=str(d.id), filename=d.filename, status=d.status, created_at=d.created_at.isoformat())


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "not found")
    # Delete Qdrant vectors for this doc (tenant-scoped filter belt-and-braces).
    qdrant.delete(
        settings.qdrant_collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(
                must=[
                    qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=user.tenant_id)),
                    qm.FieldCondition(key="document_id", match=qm.MatchValue(value=str(doc_id))),
                ]
            )
        ),
    )
    # Delete children in FK order: flagged_chunks -> chunks_meta -> (ORM cascade
    # handles parents when the document is deleted). Without this, deleting a
    # processed document violates the chunks_meta.parent_id FK and 500s.
    chunk_ids = select(ChunkMeta.id).where(ChunkMeta.document_id == doc_id)
    db.execute(delete(FlaggedChunk).where(FlaggedChunk.chunk_id.in_(chunk_ids)))
    db.execute(delete(ChunkMeta).where(ChunkMeta.document_id == doc_id))
    # Drop this document's PII vault rows too — deleting a document should not
    # leave its PII recoverable. (Tokens shared with other docs re-vault on
    # their next ingestion; acceptable for the prototype.)
    db.execute(delete(PiiVault).where(PiiVault.document_id == doc_id))
    db.delete(d)  # ORM cascade removes parents
    audit(db, tenant_id=user.tenant_id, user_id=user.user_id, action="delete",
          resource_type="document", resource_id=str(doc_id))
    return
