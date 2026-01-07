from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from models import AuditLog, User


def log_audit_event(
    db: Session,
    user: User | None,
    action: str,
    target_type: str,
    target_id: int | None = None,
    extra_data: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            extra_data=extra_data,
        )
    )
