"""Fetch full parent content for the top-ranked candidates.

Multiple children can point at the same parent — dedupe by parent_id
preserving the best rank. Postgres RLS enforces tenant scoping on the
parent read as well; the retriever's Qdrant filter is the first layer.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Document, Parent
from app.query.retriever import Candidate


@dataclass
class ContextItem:
    parent_id: str
    document_id: str
    document_filename: str
    component_type: str
    content: str
    score: float


def merge_parents(db: Session, ranked: list[Candidate], top_n: int) -> list[ContextItem]:
    # Dedupe by parent, keep best score
    seen: dict[str, Candidate] = {}
    for c in ranked:
        if c.parent_id not in seen:
            seen[c.parent_id] = c
        if len(seen) >= top_n:
            break

    ids = [uuid.UUID(pid) for pid in seen.keys()]
    if not ids:
        return []
    rows = (
        db.execute(
            select(Parent, Document.filename)
            .join(Document, Document.id == Parent.document_id)
            .where(Parent.id.in_(ids))
        )
        .all()
    )
    parents_by_id = {str(p.id): (p, filename) for p, filename in rows}
    out: list[ContextItem] = []
    for pid, cand in seen.items():
        row = parents_by_id.get(pid)
        if not row:
            continue
        parent, filename = row
        out.append(
            ContextItem(
                parent_id=pid,
                document_id=str(parent.document_id),
                document_filename=filename,
                component_type=parent.component_type,
                content=parent.content,
                score=cand.score,
            )
        )
    return out


def person_anchors(
    db: Session,
    person_tokens: list[str],
    document_ids: list[str],
    exclude_parent_ids: set[str],
    per_token: int = 1,
) -> list[ContextItem]:
    """Fetch 'identity anchor' parents: blocks from the retrieved documents
    that CONTAIN a person token from the (grounded) question.

    Names are masked at ingestion, so the chunk holding a fact ("Closing
    Balance: ...") usually does not identify whose record it is — that lives
    in a sibling block ("Account Holder: [PERSON_...]") which may not rank
    into the top-N on its own. Without the anchor in context, the LLM cannot
    tie the fact to the asked-about person and must refuse. This pins the
    anchor into the context. RLS scopes the read to the caller's tenant.
    """
    if not person_tokens or not document_ids:
        return []
    doc_uuids = [uuid.UUID(d) for d in set(document_ids)]
    out: list[ContextItem] = []
    for tok in dict.fromkeys(person_tokens):  # preserve order, dedupe
        rows = db.execute(
            select(Parent, Document.filename)
            .join(Document, Document.id == Parent.document_id)
            .where(Parent.document_id.in_(doc_uuids))
            # strpos instead of LIKE: tokens contain '_' which LIKE treats
            # as a single-char wildcard.
            .where(func.strpos(Parent.content, tok) > 0)
            .limit(per_token + len(exclude_parent_ids))
        ).all()
        added = 0
        for p, filename in rows:
            pid = str(p.id)
            if pid in exclude_parent_ids:
                continue
            out.append(
                ContextItem(
                    parent_id=pid,
                    document_id=str(p.document_id),
                    document_filename=filename,
                    component_type=p.component_type,
                    content=p.content,
                    score=1.0,
                )
            )
            exclude_parent_ids.add(pid)
            added += 1
            if added >= per_token:
                break
    return out
