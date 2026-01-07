from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import Notification, User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notification_type: str
    message: str
    target_url: str | None = None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    unread_count: int
    notifications: list[NotificationOut]


def _notifications_base_query(db: Session, current_user: User):
    return db.query(Notification).filter(
        or_(
            Notification.recipient_user_id == current_user.id,
            Notification.recipient_role == current_user.role,
        )
    )


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    unread_only: bool = False,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    limit = max(1, min(limit, 50))
    since_date = datetime.utcnow() - timedelta(days=30)
    base_query = _notifications_base_query(db, current_user).filter(
        Notification.created_at >= since_date
    )
    unread_count = (
        base_query.filter(Notification.is_read.is_(False)).count()
    )
    if unread_only:
        base_query = base_query.filter(Notification.is_read.is_(False))
    notifications = (
        base_query.order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return NotificationListResponse(
        unread_count=unread_count,
        notifications=notifications,
    )


@router.get("/poll", response_model=NotificationListResponse)
def poll_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    base_query = _notifications_base_query(db, current_user)
    unread_count = (
        base_query.filter(Notification.is_read.is_(False)).count()
    )
    notifications = (
        base_query.order_by(Notification.created_at.desc())
        .limit(5)
        .all()
    )
    return NotificationListResponse(
        unread_count=unread_count,
        notifications=notifications,
    )


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    notification = (
        _notifications_base_query(db, current_user)
        .filter(Notification.id == notification_id)
        .first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notifica non trovata")
    if not notification.is_read:
        notification.is_read = True
        db.add(notification)
        db.commit()
        db.refresh(notification)
    return notification
