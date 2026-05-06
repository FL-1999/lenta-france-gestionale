from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_
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
    notifications: list[NotificationRecentItem]


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadRequest(BaseModel):
    notification_id: int | None = None
    mark_all: bool = False


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


def _serialize_recent_notification(notification: Notification) -> NotificationRecentItem:
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
    base_query = _notifications_base_query(db, current_user)
    unread_count = (
        base_query.filter(Notification.is_read.is_(False)).count()
    )
    return UnreadCountResponse(unread_count=unread_count)


@router.get("/list", response_model=NotificationListPayload)
def list_latest_notifications(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    limit = max(1, min(limit, 50))
    base_query = _notifications_base_query(db, current_user)
    unread_count = (
        base_query.filter(Notification.is_read.is_(False)).count()
    )
    notifications = base_query.order_by(Notification.created_at.desc()).limit(limit).all()
    return NotificationListPayload(
        unread_count=unread_count,
        notifications=[_serialize_notification(n) for n in notifications],
    )




@router.get("/recent", response_model=NotificationRecentPayload)
def list_recent_notifications(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    limit = max(1, min(limit, 50))
    notifications = (
        _notifications_recent_or_unread_query(db, current_user)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return NotificationRecentPayload(
        notifications=[_serialize_recent_notification(n) for n in notifications],
    )

@router.post("/mark-read", response_model=UnreadCountResponse)
def mark_notifications_read(
    payload: MarkReadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    base_query = _notifications_base_query(db, current_user)
    if payload.mark_all:
        (
            base_query.filter(Notification.is_read.is_(False))
            .update({"is_read": True}, synchronize_session=False)
        )
        db.commit()
    elif payload.notification_id is not None:
        notification = (
            base_query.filter(Notification.id == payload.notification_id)
            .first()
        )
        if not notification:
            raise HTTPException(status_code=404, detail="Notifica non trovata")
        if not notification.is_read:
            notification.is_read = True
            db.add(notification)
            db.commit()
            db.refresh(notification)
    else:
        raise HTTPException(status_code=400, detail="Nessuna notifica selezionata")
    unread_count = (
        base_query.filter(Notification.is_read.is_(False)).count()
    )
    return UnreadCountResponse(unread_count=unread_count)


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    unread_only: bool = False,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    limit = max(1, min(limit, 50))
    base_query = _notifications_recent_or_unread_query(db, current_user)
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
    current_user: User = Depends(get_current_active_user_api),
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
    current_user: User = Depends(get_current_active_user_api),
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
