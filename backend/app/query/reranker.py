from functools import lru_cache

from app.config import settings
from app.query.retriever import Candidate


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import CrossEncoder

    # Same meta-tensor fix as the embedder — disable low_cpu_mem_usage so
    # weights load directly on the target device.
    return CrossEncoder(
        settings.reranker_model,
        device=settings.device,
        max_length=512,
        model_kwargs={"low_cpu_mem_usage": False},
    )


def rerank(question: str, candidates: list[Candidate]) -> list[Candidate]:
    if not candidates:
        return []
    pairs = [(question, c.text) for c in candidates]
    scores = _model().predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    for c, s in ranked:
        c.score = float(s)
    return [c for c, _ in ranked]
