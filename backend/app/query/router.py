import time
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit.logger import audit
from app.config import settings
from app.deps import CurrentUser, get_current_user, get_db
from app.ingestion.pii_mask import find_tokens
from app.ingestion.pii_vault import unmask as vault_unmask
from app.query.context_scan import scan_context
from app.query.llm import complete
from app.query.parent_merge import merge_parents, person_anchors
from app.query.person_grounding import ground_question
from app.query.prompt import SYSTEM, build_prompt
from app.query.reranker import rerank
from app.query.retriever import search

log = logging.getLogger(__name__)

router = APIRouter()


class QueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = None


class Citation(BaseModel):
    tag: str
    document_id: str
    filename: str
    parent_id: str
    snippet: str


class QueryOut(BaseModel):
    answer: str
    citations: list[Citation]
    latency_ms: int


REFUSAL = "I don't have enough information to answer that."


@router.post("", response_model=QueryOut)
def query(
    body: QueryIn,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()

    # 0. Person grounding: names in documents were masked into deterministic
    #    tokens at ingestion, so resolve names in the QUESTION to the same
    #    tokens (RLS-scoped vault lookup). If the question is about people
    #    and NONE of them have data in this tenant, refuse outright — that's
    #    what prevents "Priya's balance" being answered with another
    #    customer's (or another tenant's customer's) numbers.
    g = ground_question(db, body.question)
    flagged: list[str] = []
    sources: list[dict] = []

    if g.all_unknown:
        log.info("query refers only to unknown persons %s; refusing", g.unresolved)
        answer = REFUSAL
    else:
        if g.detected:
            # Safe to log: names are already replaced by tokens here.
            log.info("grounded question: %r (unresolved=%s)", g.question, g.unresolved)
        # 1. Retrieve (grounded question: tokens match chunk text exactly).
        candidates = search(user.tenant_id, g.question, top_k=None)
        # 2. Rerank.
        ranked = rerank(g.question, candidates)
        # 3. Parent merge + dedupe.
        items = merge_parents(db, ranked, top_n=body.top_k or settings.top_k_parents)
        # 3b. Pin identity anchors: blocks from the retrieved documents that
        #     contain the question's person token ("Account Holder: [PERSON_x]").
        #     Facts and identity live in different chunks after masking, so
        #     without this the LLM (correctly) refuses to attribute.
        ptokens = [t for t in find_tokens(g.question) if t.startswith("[PERSON_")]
        if ptokens and items:
            anchors = person_anchors(
                db, ptokens, [it.document_id for it in items], {it.parent_id for it in items}
            )
            items = anchors + items
        # 4. Query-time injection scan on the assembled context (anchors included).
        safe_items, flagged = scan_context(items)

        if not safe_items:
            answer = REFUSAL
        else:
            # 5. Build prompt with structural delimiters + system rules.
            user_msg, sources = build_prompt(g.question, safe_items, settings.context_token_budget)
            # 6. LLM call. The prompt contains ONLY masked tokens — the LLM never
            #    sees raw PII (including person names in the question). We unmask
            #    AFTER completion for the authenticated caller (whose tenant
            #    scope RLS-gates the vault lookup).
            answer = complete(SYSTEM, user_msg)

    # 7. Reveal-at-render: swap tokens like [ACCOUNT_NUMBER_abcd1234] back to
    #    their originals for the caller. Vault RLS ensures only this tenant's
    #    values are visible. Can be disabled via PII_UNMASK_ON_QUERY=false.
    if settings.pii_unmask_on_query:
        answer_before = answer
        answer = vault_unmask(db, answer)
        if answer_before == answer:
            tokens = find_tokens(answer_before)
            if tokens:
                log.warning(
                    "PII unmask did not replace any tokens for tenant %s; tokens=%s",
                    user.tenant_id,
                    tokens,
                )
            else:
                log.debug("PII unmask found no tokens in answer text")

        for s in sources:
            snippet_before = s["snippet"]
            s["snippet"] = vault_unmask(db, snippet_before)
            if snippet_before == s["snippet"]:
                tokens = find_tokens(snippet_before)
                if tokens:
                    log.warning(
                        "PII unmask did not replace any tokens in snippet for parent %s; tokens=%s",
                        s["parent_id"],
                        tokens,
                    )

    latency = int((time.perf_counter() - t0) * 1000)
    audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="query",
        resource_type="query",
        meta={
            "question": body.question[:500],
            "parents": [s["parent_id"] for s in sources],
            "flagged_at_query": flagged,
            "unresolved_persons": g.unresolved,
            "latency_ms": latency,
        },
    )
    return QueryOut(
        answer=answer,
        citations=[Citation(**s) for s in sources],
        latency_ms=latency,
    )
