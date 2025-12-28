from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user_html
from database import get_db
from models import AuditLog, RoleEnum, User


templates = Jinja2Templates(directory="templates")
router = APIRouter(tags=["audit"])


def _ensure_admin_or_manager(user: User) -> None:
    if user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@router.get("/manager/audit", response_class=HTMLResponse, name="manager_audit_list")
def manager_audit_list(
    request: Request,
    azione: str | None = None,
    user_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_admin_or_manager(current_user)

    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)

    query = db.query(AuditLog).options(joinedload(AuditLog.user))
    if azione:
        query = query.filter(AuditLog.azione == azione)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if parsed_from:
        query = query.filter(
            AuditLog.created_at >= datetime.combine(parsed_from, time.min)
        )
    if parsed_to:
        query = query.filter(
            AuditLog.created_at <= datetime.combine(parsed_to, time.max)
        )

    logs = query.order_by(AuditLog.created_at.desc()).all()
    utenti = db.query(User).order_by(User.full_name.asc(), User.email.asc()).all()
    azioni = [
        row[0]
        for row in db.query(AuditLog.azione)
        .distinct()
        .order_by(AuditLog.azione.asc())
        .all()
        if row[0]
    ]

    return templates.TemplateResponse(
        "manager/audit_list.html",
        {
            "request": request,
            "user": current_user,
            "logs": logs,
            "utenti": utenti,
            "azioni": azioni,
            "filtri": {
                "azione": azione or "",
                "user_id": user_id or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        },
    )
