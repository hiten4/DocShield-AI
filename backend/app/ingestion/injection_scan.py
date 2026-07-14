"""Prompt-injection classifier (per chunk at ingestion; whole context at query time).

Uses `protectai/deberta-v3-base-prompt-injection` — a small, fast HF classifier.
Falls back to a heuristic regex list if the model can't be loaded (offline dev).
"""

import logging
import re
from functools import lru_cache

from app.config import settings

log = logging.getLogger(__name__)

_HEURISTIC_PATTERNS = [
    re.compile(r"(?i)ignore (?:all )?(?:previous|prior|above) (?:instructions|prompts?)"),
    re.compile(r"(?i)disregard (?:the )?system prompt"),
    re.compile(r"(?i)you are now (?:a|an|the)\b"),
    re.compile(r"(?i)(?:tell|reveal|print) (?:me )?(?:the )?(?:system|hidden) prompt"),
    re.compile(r"(?i)act as (?:a|an)? ?(?:jailbroken|dan|unrestricted)"),
    re.compile(r"(?i)override (?:the )?safety"),
]


@lru_cache(maxsize=1)
def _model():
    try:
        from transformers import pipeline

        return pipeline(
            "text-classification",
            model=settings.injection_model,
            device=-1,
            truncation=True,
        )
    except Exception as e:  # network unavailable, model missing, etc.
        log.warning("injection model unavailable, using heuristics only: %s", e)
        return None


def classify(text: str) -> tuple[bool, float, str]:
    """Returns (is_injection, score, reason)."""
    text = text.strip()
    if not text:
        return False, 0.0, ""
    for p in _HEURISTIC_PATTERNS:
        if p.search(text):
            return True, 1.0, f"heuristic:{p.pattern[:40]}"

    m = _model()
    if m is None:
        return False, 0.0, ""
    try:
        out = m(text[:2000])  # cap for speed
        # Model returns [{"label": "INJECTION"|"SAFE", "score": 0..1}]
        label = out[0]["label"].upper()
        score = float(out[0]["score"])
        if label == "INJECTION" and score >= settings.injection_threshold:
            return True, score, f"model:{label}:{score:.2f}"
        return False, score, ""
    except Exception as e:
        log.warning("injection model call failed: %s", e)
        return False, 0.0, ""
