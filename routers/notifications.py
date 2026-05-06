from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from auth import get_current_active_user_api
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


class NotificationListItem(BaseModel):
    id: int
    message: str
    link_url: str | None = None
    read: bool
    created_at: datetime


class NotificationRecentItem(BaseModel):
    id: int
    message: str
    created_at: str
    url: str | None = None
    is_read: bool


class NotificationListPayload(BaseModel):
    unread_count: int
    notifications: list[NotificationListItem]


class NotificationRecentPayload(BaseModel):
    unread_count: int
    notifications: list[NotificationRecentItem]


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadRequest(BaseModel):
    notification_id: int | None = None
    mark_all: bool = False


class ClearAllResponse(BaseModel):
    deleted_count: int
    unread_count: int


def _cleanup_stale_notifications(db: Session, current_user: User) -> None:
    """Keep the notification table bounded for the current user/role."""
    cutoff = datetime.utcnow() - timedelta(days=30)
    direct_base = _notifications_base_query(db, current_user)

    old_read_ids = [
        row[0]
        for row in direct_base.filter(
            Notification.is_read.is_(True),
            Notification.created_at < cutoff,
        )
        .with_entities(Notification.id)
        .all()
    ]

    direct_keep_ids = [
        row[0]
        for row in db.query(Notification.id)
        .filter(Notification.recipient_user_id == current_user.id)
        .order_by(Notification.is_read.asc(), Notification.created_at.desc())
        .limit(100)
        .all()
    ]
    direct_extra_ids = [
        row[0]
        for row in db.query(Notification.id)
        .filter(Notification.recipient_user_id == current_user.id)
        .filter(~Notification.id.in_(direct_keep_ids) if direct_keep_ids else True)
        .with_entities(Notification.id)
        .all()
    ]

    role_keep_ids = [
        row[0]
        for row in db.query(Notification.id)
        .filter(Notification.recipient_role == current_user.role)
        .order_by(Notification.is_read.asc(), Notification.created_at.desc())
        .limit(100)
        .all()
    ]
    role_extra_ids = [
        row[0]
        for row in db.query(Notification.id)
        .filter(Notification.recipient_role == current_user.role)
        .filter(~Notification.id.in_(role_keep_ids) if role_keep_ids else True)
        .with_entities(Notification.id)
        .all()
    ]

    notification_ids = set(old_read_ids + direct_extra_ids + role_extra_ids)
    if not notification_ids:
        return

    db.execute(delete(Notification).where(Notification.id.in_(notification_ids)))
    db.commit()


def _notifications_base_query(db: Session, current_user: User):
    return db.query(Notification).filter(
        or_(
            Notification.recipient_user_id == current_user.id,
            Notification.recipient_role == current_user.role,
        )
    )


def _notifications_recent_or_unread_query(db: Session, current_user: User):
    since_date = datetime.utcnow() - timedelta(days=30)
    return _notifications_base_query(db, current_user).filter(
        or_(
            Notification.created_at >= since_date,
            Notification.is_read.is_(False),
        )
    )


def _serialize_notification(notification: Notification) -> NotificationListItem:
    return NotificationListItem(
        id=notification.id,
        message=notification.message,
        link_url=notification.target_url,
        read=notification.is_read,
        created_at=notification.created_at,
    )


def _format_recent_created_at(created_at: datetime) -> str:
    return created_at.strftime("%d/%m/%Y %H:%M")


def _serialize_recent_notification(
    notification: Notification,
) -> NotificationRecentItem:
    return NotificationRecentItem(
        id=notification.id,
        message=notification.message,
        created_at=_format_recent_created_at(notification.created_at),
        url=notification.target_url,
        is_read=notification.is_read,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    _cleanup_stale_notifications(db, current_user)
    base_query = _notifications_base_query(db, current_user)
    unread_count = base_query.filter(Notification.is_read.is_(False)).count()
    return UnreadCountResponse(unread_count=unread_count)


@router.get("/list", response_model=NotificationListPayload)
def list_latest_notifications(
    limit: int = 15,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    _cleanup_stale_notifications(db, current_user)
    limit = max(1, min(limit, 15))
    base_query = _notifications_base_query(db, current_user)
    unread_count = base_query.filter(Notification.is_read.is_(False)).count()
    notifications = (
        base_query.order_by(Notification.is_read.asc(), Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return NotificationListPayload(
        unread_count=unread_count,
        notifications=[_serialize_notification(n) for n in notifications],
    )


@router.get("/recent", response_model=NotificationRecentPayload)
def list_recent_notifications(
    limit: int = 15,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    _cleanup_stale_notifications(db, current_user)
    limit = max(1, min(limit, 15))
    base_query = _notifications_recent_or_unread_query(db, current_user)
    unread_count = base_query.filter(Notification.is_read.is_(False)).count()
    notifications = (
        base_query.order_by(Notification.is_read.asc(), Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return NotificationRecentPayload(
        unread_count=unread_count,
        notifications=[_serialize_recent_notification(n) for n in notifications],
    )


@router.post("/mark-read", response_model=UnreadCountResponse)
def mark_notifications_read(
    payload: MarkReadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    _cleanup_stale_notifications(db, current_user)
    base_query = _notifications_base_query(db, current_user)
    if payload.mark_all:
        (
            base_query.filter(Notification.is_read.is_(False)).update(
                {"is_read": True}, synchronize_session=False
            )
        )
        db.commit()
    elif payload.notification_id is not None:
        notification = base_query.filter(
            Notification.id == payload.notification_id
        ).first()
        if not notification:
            raise HTTPException(status_code=404, detail="Notifica non trovata")
        if not notification.is_read:
            notification.is_read = True
            db.add(notification)
            db.commit()
            db.refresh(notification)
    else:
        raise HTTPException(status_code=400, detail="Nessuna notifica selezionata")
    unread_count = base_query.filter(Notification.is_read.is_(False)).count()
    return UnreadCountResponse(unread_count=unread_count)


@router.post("/clear-all", response_model=ClearAllResponse)
def clear_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    _cleanup_stale_notifications(db, current_user)
    base_query = _notifications_base_query(db, current_user)
    notification_ids = [
        row[0] for row in base_query.with_entities(Notification.id).all()
    ]
    if notification_ids:
        db.execute(delete(Notification).where(Notification.id.in_(notification_ids)))
        db.commit()
    unread_count = (
        _notifications_base_query(db, current_user)
        .filter(Notification.is_read.is_(False))
        .count()
    )
    return ClearAllResponse(
        deleted_count=len(notification_ids),
        unread_count=unread_count,
    )


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    unread_only: bool = False,
    limit: int = 15,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    _cleanup_stale_notifications(db, current_user)
    limit = max(1, min(limit, 15))
    base_query = _notifications_recent_or_unread_query(db, current_user)
    unread_count = base_query.filter(Notification.is_read.is_(False)).count()
    if unread_only:
        base_query = base_query.filter(Notification.is_read.is_(False))
    notifications = (
        base_query.order_by(Notification.is_read.asc(), Notification.created_at.desc())
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
    current_user: User = Depends(get_current_active_user_api),
):
    _cleanup_stale_notifications(db, current_user)
    base_query = _notifications_base_query(db, current_user)
    unread_count = base_query.filter(Notification.is_read.is_(False)).count()
    notifications = (
        base_query.order_by(Notification.is_read.asc(), Notification.created_at.desc())
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
    current_user: User = Depends(get_current_active_user_api),
):
    _cleanup_stale_notifications(db, current_user)
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
