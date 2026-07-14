"""Ground person references in a query against the tenant's PII vault.

Names are PII-masked into deterministic tokens at ingestion, so the vector
store and the LLM never see raw names. That breaks person-attributed
questions ("What is Priya's closing balance?") in two ways:

1. The LLM cannot tell WHICH masked person a fact belongs to, so it happily
   misattributes another customer's numbers to the asked-about person.
2. A question about a person with NO data in this tenant looks identical to
   a question about a real customer — so instead of refusing, the model
   answers from whichever records were retrieved.

Fix: detect PERSON spans in the question, resolve them against the tenant's
vault (an RLS-scoped read — only this tenant's names are visible), and
substitute the person's deterministic token into the question. Then:

- Retrieval and reranking see the exact token string that ingestion wrote
  into the chunks, so the right person's chunks rank up.
- The LLM can match the question's token against context tokens.
- If a detected person resolves to nothing, that person has no data in this
  tenant — the router refuses BEFORE calling the LLM.

Partial names work ("Kavita" matches vault entry "Kavita Reddy") via
case-insensitive containment in either direction.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PiiVault
from app.ingestion.pii_mask import _analyzer
from app.ingestion.pii_vault import decrypt

log = logging.getLogger(__name__)

_MAX_VAULT_SCAN = 5000


@dataclass
class Grounding:
    question: str  # question with resolved names replaced by their tokens
    detected: list[str] = field(default_factory=list)  # person names found
    unresolved: list[str] = field(default_factory=list)  # names unknown to this tenant

    @property
    def all_unknown(self) -> bool:
        """True when the question names people but NONE have data in this tenant."""
        return bool(self.detected) and len(self.unresolved) == len(self.detected)


def _tenant_person_map(db: Session) -> dict[str, str]:
    """{lowercased original name: token} for the CURRENT tenant (RLS-scoped)."""
    rows = db.execute(
        select(PiiVault.token, PiiVault.encrypted_value)
        .where(PiiVault.entity_type == "PERSON")
        .limit(_MAX_VAULT_SCAN)
    ).all()
    out: dict[str, str] = {}
    for token, blob in rows:
        try:
            out[decrypt(blob).lower()] = token
        except Exception:
            continue
    return out


def _match(name: str, persons: dict[str, str]) -> str | None:
    """Exact match first, then containment either way ("Kavita" ~ "Kavita Reddy")."""
    n = name.lower().strip()
    if n in persons:
        return persons[n]
    for full, token in persons.items():
        if n in full or full in n:
            return token
    return None


def ground_question(db: Session, question: str) -> Grounding:
    try:
        results = _analyzer().analyze(text=question, language="en", entities=["PERSON"])
    except Exception as e:  # NER failure must never take the query path down
        log.warning("person grounding NER failed, skipping: %s", e)
        return Grounding(question=question)
    if not results:
        return Grounding(question=question)

    persons = _tenant_person_map(db)
    detected: list[str] = []
    unresolved: list[str] = []
    # Replace right-to-left so earlier spans stay valid after substitution.
    for r in sorted(results, key=lambda r: r.start, reverse=True):
        name = question[r.start : r.end]
        detected.append(name)
        token = _match(name, persons)
        if token:
            question = question[: r.start] + token + question[r.end :]
        else:
            unresolved.append(name)
    return Grounding(question=question, detected=detected, unresolved=unresolved)
