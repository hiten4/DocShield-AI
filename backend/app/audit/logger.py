import uuid

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def audit(
    db: Session,
    *,
    tenant_id: uuid.UUID | str | None,
    user_id: uuid.UUID | str | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    meta: dict | None = None,
) -> None:
    entry = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        meta=meta or {},
    )
    db.add(entry)
    db.flush()
