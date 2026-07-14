"""Query-time injection scan on the assembled context.

Runs the same classifier over the full merged text (and each parent
individually) because a chunk that looked safe alone can look adversarial
when combined with its neighbors.
"""

from app.ingestion.injection_scan import classify
from app.query.parent_merge import ContextItem


def scan_context(items: list[ContextItem]) -> tuple[list[ContextItem], list[str]]:
    """Returns (safe_items, flagged_parent_ids)."""
    safe: list[ContextItem] = []
    flagged: list[str] = []
    for it in items:
        is_inj, _, _ = classify(it.content)
        if is_inj:
            flagged.append(it.parent_id)
        else:
            safe.append(it)
    # Also scan the concatenation — some attacks only trigger at scale.
    if safe:
        combined = "\n\n".join(it.content for it in safe)
        is_inj, _, _ = classify(combined[:8000])
        if is_inj:
            # Nothing survives — signal to router to refuse.
            return [], [it.parent_id for it in items]
    return safe, flagged
