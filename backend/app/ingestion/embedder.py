from functools import lru_cache

from app.config import settings


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    # low_cpu_mem_usage=False avoids the "meta tensor" load path that requires
    # `accelerate` — without it, .to(device) raises NotImplementedError on
    # sentence-transformers >= 3.1 with torch 2.4.
    return SentenceTransformer(
        settings.embedding_model,
        device=settings.device,
        model_kwargs={"low_cpu_mem_usage": False},
    )


def embed_batch(texts: list[str]) -> list[list[float]]:
    m = _model()
    vecs = m.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> list[float]:
    # bge convention: prefix queries with a retrieval instruction
    if "bge" in settings.embedding_model.lower():
        text = "Represent this sentence for searching relevant passages: " + text
    return embed_batch([text])[0]
