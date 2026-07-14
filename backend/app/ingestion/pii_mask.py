"""PII masking: Presidio (NER) + custom regex, with vault mapping.

Applied BEFORE embedding so raw PII never enters the vector store or the LLM
prompt. Returns (masked_text, mapping) where mapping is
    {token: (entity_type, original_value)}
so the caller (ingestion pipeline) can persist it to the encrypted per-tenant
`pii_vault` table. Tokens are shaped like `[ENTITY_TYPE_abcd1234]` — the hex
suffix is a deterministic hash of (entity_type, value), so the same PII value
gets the same token wherever it appears within a tenant.
"""

import hashlib
import re
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig


# ---------------------------------------------------------------------------
# Verhoeff checksum — used to reject 12-digit numbers that aren't real Aadhaar.
# ---------------------------------------------------------------------------
_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_valid(num: str) -> bool:
    digits = re.sub(r"\s+", "", num)
    if not digits.isdigit() or len(digits) != 12:
        return False
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(d)]]
    return c == 0


# ---------------------------------------------------------------------------
# Token generation. Deterministic per (entity_type, value) — so the same
# real value produces the same token, keeping references consistent for
# the LLM ("[EMAIL_ADDRESS_abc1] and [EMAIL_ADDRESS_abc1] are the same").
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"\[([A-Z_]+)_([a-f0-9]{8})\]")


def make_token(entity_type: str, value: str) -> str:
    h = hashlib.sha256(f"{entity_type}|{value}".encode("utf-8")).hexdigest()[:8]
    return f"[{entity_type}_{h}]"


# ---------------------------------------------------------------------------
# Label-anchored patterns. These use a capture group so we know which slice
# of the match is the actual sensitive value; the surrounding label stays
# visible in the masked text.
#
# Order matters: earlier entries are tried first per-block and later
# patterns will not re-tokenize an already-tokenized span.
# ---------------------------------------------------------------------------
_LABELED_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ACCOUNT_NUMBER", re.compile(r"(?i)\baccount\s*(?:number|no\.?|#|num)\s*[:=\-]?\s*(\d{9,18})\b")),
    ("CUSTOMER_ID",    re.compile(r"(?i)\bcustomer\s*id\s*[:=\-]?\s*([A-Za-z0-9]{3,20})\b")),
    # Client IDs are frequently alphanumeric with dashes ("CID-12345"),
    # not digits-only — a digits-only pattern silently leaks them.
    ("CLIENT_ID",      re.compile(r"(?i)\bclient\s*id\s*[:=\-]?\s*([A-Za-z0-9\-]{3,40})\b")),
    ("PASSWORD_FIELD", re.compile(r"(?i)\bpassword\s*[:=]\s*(\S+)")),
    ("API_KEY",        re.compile(r"(?i)\b(?:api[_-]?key|secret)\s*[:=]\s*([A-Za-z0-9\-_]{16,})\b")),
    ("NATIONAL_ID",    re.compile(r"\b(\d{3}-\d{2}-\d{4})\b")),  # US SSN shape
]


# ---------------------------------------------------------------------------
# Presidio: used only for NER-driven entity types (PERSON, EMAIL, PHONE,
# addresses via NER, etc.) plus a strict AADHAAR pattern with Verhoeff
# validation. Label-anchored entities are handled OUTSIDE Presidio because
# we want to preserve the label in the output ("Account Number : [TOKEN]").
# ---------------------------------------------------------------------------
_NER_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IBAN_CODE",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "AADHAAR",
]


class _AadhaarRecognizer(PatternRecognizer):
    """Aadhaar recognizer that rejects candidates failing the Verhoeff check."""

    def validate_result(self, pattern_text: str) -> bool:
        return _verhoeff_valid(pattern_text)


_NLP_CONFIG = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
}


# ---------------------------------------------------------------------------
# PERSON plausibility filter. en_core_web_sm has bad precision on financial
# documents — it tags capitalized domain phrases ("Closing Balance", "Fixed
# Deposit") as PERSON. Masking those (a) attaches a bogus person-token to the
# fact chunk, which makes the query-side person grounding refuse legitimate
# questions, and (b) deletes the key phrase from the embedded text, wrecking
# retrieval. Reject PERSON spans that contain domain vocabulary or don't look
# like names.
# ---------------------------------------------------------------------------
_PERSON_STOPWORDS = frozenset("""
account balance statement bank banking deposit deposits fixed recurring
interest rate rates loan loans credit debit card insurance policy premium
portfolio holding holdings return returns branch total opening closing
summary agreement transaction transactions transfer payment payments payroll
mortgage market period email phone number client customer address street road
date amount value fee fees charge charges tax fund funds equity mutual
savings current annual monthly quarterly wire threshold approval admin system
note instructions terms conditions maintenance sanction sanctioned draw
repayment collateral appraised whole foods
""".split())


def _plausible_person(value: str) -> bool:
    words = re.findall(r"[A-Za-z]+", value)
    if not words or len(words) > 4:
        return False
    if any(w.lower() in _PERSON_STOPWORDS for w in words):
        return False
    # Names are capitalized; reject all-lower/all-upper shouting spans.
    if not all(w[0].isupper() for w in words):
        return False
    return True


@lru_cache(maxsize=1)
def _analyzer() -> AnalyzerEngine:
    provider = NlpEngineProvider(nlp_configuration=_NLP_CONFIG)
    a = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
    a.registry.add_recognizer(
        _AadhaarRecognizer(
            supported_entity="AADHAAR",
            patterns=[Pattern(name="aadhaar", regex=r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b", score=0.6)],
        )
    )
    return a


@lru_cache(maxsize=1)
def _anonymizer() -> AnonymizerEngine:
    return AnonymizerEngine()


def mask_text(text: str) -> tuple[str, dict[str, tuple[str, str]]]:
    """Mask PII in `text`.

    Returns (masked_text, {token: (entity_type, original_value)}). The mapping
    is the caller's responsibility to persist to the encrypted vault. This
    function itself is stateless; multiple calls with the same value produce
    the same token.
    """
    mapping: dict[str, tuple[str, str]] = {}
    if not text.strip():
        return text, mapping

    # Pass 1: label-anchored regex. We replace only the captured group so the
    # label survives ("Account Number : [ACCOUNT_NUMBER_abcd1234]").
    def _replace_with_token(match: re.Match, entity_type: str) -> str:
        value = match.group(1)
        # Don't re-tokenize an already-tokenized value.
        if _TOKEN_RE.fullmatch(value):
            return match.group(0)
        token = make_token(entity_type, value)
        mapping[token] = (entity_type, value)
        return match.group(0)[: match.start(1) - match.start()] + token + match.group(0)[match.end(1) - match.start():]

    for entity_type, pattern in _LABELED_PATTERNS:
        text = pattern.sub(lambda m, et=entity_type: _replace_with_token(m, et), text)

    # Pass 2: Presidio NER for names, emails, phones, and validated Aadhaar.
    # We use a "custom" operator per entity so each match gets tokenized (not
    # just replaced with a static "[EMAIL]" string).
    analyzer = _analyzer()
    anonymizer = _anonymizer()
    results = analyzer.analyze(text=text, language="en", entities=_NER_ENTITIES)
    # Drop implausible PERSON detections (see _plausible_person).
    results = [
        r
        for r in results
        if r.entity_type != "PERSON" or _plausible_person(text[r.start : r.end])
    ]

    def _op_for(entity_type: str):
        def _fn(original: str) -> str:
            if _TOKEN_RE.fullmatch(original):
                return original
            token = make_token(entity_type, original)
            mapping[token] = (entity_type, original)
            return token
        return OperatorConfig("custom", {"lambda": _fn})

    ops = {e: _op_for(e) for e in _NER_ENTITIES}
    anonymized = anonymizer.anonymize(text=text, analyzer_results=results, operators=ops)
    return anonymized.text, mapping


def find_tokens(text: str) -> list[str]:
    """Return every mask token found in `text`."""
    return [m.group(0) for m in _TOKEN_RE.finditer(text)]
