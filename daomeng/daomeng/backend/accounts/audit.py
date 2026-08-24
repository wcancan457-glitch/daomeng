from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from accounts.models import AdminAuditLog


def record_admin_action(
    db: Session,
    *,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str = "",
    details: dict[str, Any] | None = None,
) -> AdminAuditLog:
    record = AdminAuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details or {},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
