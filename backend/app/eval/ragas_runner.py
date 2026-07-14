"""RAGAS evaluation runner.

Feeds a small golden-Q&A set through the query pipeline and returns the
four metrics. Meant for offline/admin use — RAGAS itself consumes an LLM.
"""

import json
import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import EvalRun
from app.query.parent_merge import merge_parents
from app.query.prompt import SYSTEM, build_prompt
from app.query.reranker import rerank
from app.query.retriever import search
from app.query.llm import complete

log = logging.getLogger(__name__)


def _run_pipeline(db: Session, tenant_id: str, question: str) -> tuple[str, list[str]]:
    cands = search(tenant_id, question)
    ranked = rerank(question, cands)
    items = merge_parents(db, ranked, top_n=settings.top_k_parents)
    if not items:
        return "I don't have enough information to answer that.", []
    user_msg, sources = build_prompt(question, items, settings.context_token_budget)
    ans = complete(SYSTEM, user_msg)
    return ans, [it.content for it in items]


def run_ragas(db: Session, tenant_id: str, golden_path: str | None = None) -> dict:
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    path = Path(golden_path or Path(__file__).parent.parent / "seed" / "golden_qa.json")
    golden = json.loads(path.read_text())

    rows = []
    for item in golden:
        ans, ctx = _run_pipeline(db, tenant_id, item["question"])
        rows.append(
            {
                "question": item["question"],
                "answer": ans,
                "contexts": ctx or [""],
                "ground_truth": item.get("ground_truth", ""),
            }
        )
        db.add(
            EvalRun(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(tenant_id),
                query=item["question"],
                answer=ans,
            )
        )

    ds = Dataset.from_list(rows)
    result = evaluate(
        ds,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    )
    return {k: float(v) for k, v in result.to_pandas().mean(numeric_only=True).items()}
