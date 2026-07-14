"""Encrypted per-tenant vault for PII mask tokens.

Writes happen during ingestion (`write_mapping`); reads happen during query
(`resolve_tokens`) to unmask the LLM's answer for authenticated callers.
Tenant scoping is enforced by Postgres RLS on the `pii_vault` table — this
module never accepts a tenant_id from the caller for reads.

Values are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256). The
key comes from settings.pii_vault_key. Rotating the key is a manual
migration — out of scope here.
"""

import logging
import uuid
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import PiiVault
from app.ingestion.pii_mask import find_tokens

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.pii_vault_key
    if not key:
        raise RuntimeError(
            "PII_VAULT_KEY not set; refuse to start rather than store PII in plaintext"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt(blob: bytes) -> str:
    try:
        return _fernet().decrypt(bytes(blob)).decode("utf-8")
    except InvalidToken:
        log.error("failed to decrypt pii_vault row — key rotation or tamper?")
        raise


def write_mapping(
    db: Session,
    tenant_id: str,
    document_id: str,
    mapping: dict[str, tuple[str, str]],
) -> int:
    """Upsert {token: (entity_type, original_value)} for the given tenant/doc.

    Same token in multiple docs is fine — we upsert on (tenant_id, token), so
    the first-seen document_id sticks. Returns the number of rows attempted.
    """
    if not mapping:
        return 0
    tid = uuid.UUID(tenant_id)
    did = uuid.UUID(document_id) if document_id else None
    rows = [
        {
            "tenant_id": tid,
            "token": token,
            "entity_type": entity_type,
            "encrypted_value": encrypt(value),
            "document_id": did,
        }
        for token, (entity_type, value) in mapping.items()
    ]
    stmt = pg_insert(PiiVault).values(rows).on_conflict_do_nothing(
        index_elements=["tenant_id", "token"]
    )
    db.execute(stmt)
    return len(rows)


def resolve_tokens(db: Session, tokens: list[str]) -> dict[str, str]:
    """Return {token: original_value} for whatever tokens the CURRENT tenant
    can see. Tenant scoping is enforced by RLS on the `pii_vault` table —
    do NOT pass tenant_id in here."""
    if not tokens:
        return {}
    rows = db.execute(
        select(PiiVault.token, PiiVault.encrypted_value).where(PiiVault.token.in_(tokens))
    ).all()
    out: dict[str, str] = {}
    for token, blob in rows:
        try:
            out[token] = decrypt(blob)
        except InvalidToken:
            continue
    return out


def unmask(db: Session, text: str) -> str:
    """Replace every mask token in `text` with its original value for the
    caller's tenant. Tokens for which no mapping exists (e.g. from a
    different tenant) are left alone."""
    tokens = find_tokens(text)
    if not tokens:
        return text
    resolved = resolve_tokens(db, list(set(tokens)))
    if not resolved:
        log.debug("PII unmask found tokens but no vault mappings for tenant; tokens=%s", tokens)
        return text
    missing = [token for token in tokens if token not in resolved]
    if missing:
        log.debug("PII unmask missing vault mappings for tokens=%s", missing)
    for token, original in resolved.items():
        text = text.replace(token, original)
    log.debug("PII unmask replaced %d tokens", len(resolved))
    return text
