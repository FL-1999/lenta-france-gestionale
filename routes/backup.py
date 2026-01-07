from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from audit_utils import log_audit_event
from auth import get_current_active_user_html
from backup_utils import create_database_backup, get_backup_path, list_backups
from database import get_db
from models import User
from template_context import register_manager_badges, render_template
from permissions import has_perm


templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["backup"])


def _ensure_admin(user: User) -> None:
    if not has_perm(user, "settings.manage"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


@router.get(
    "/admin/backup-export",
    response_class=HTMLResponse,
    name="admin_backup_export",
)
def backup_export_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_admin(current_user)
    backups = list_backups()
    return render_template(
        templates,
        request,
        "admin/backup_export.html",
        {
            "backups": backups,
        },
        db,
        current_user,
    )


@router.post(
    "/admin/backup-export/run",
    response_class=RedirectResponse,
    name="admin_backup_export_run",
)
def backup_export_run(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_admin(current_user)
    backup_path = create_database_backup()
    log_audit_event(
        db,
        current_user,
        "BACKUP_MANUAL",
        "database",
        extra_data={
            "filename": backup_path.name,
            "created_at": datetime.utcnow().isoformat(),
        },
    )
    db.commit()
    return RedirectResponse(
        request.url_for("admin_backup_export"), status_code=303
    )


@router.get(
    "/admin/backup-export/download/{filename}",
    response_class=FileResponse,
    name="admin_backup_export_download",
)
def backup_export_download(
    filename: str,
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_admin(current_user)
    backup_path = get_backup_path(filename)
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="Backup non trovato")
    return FileResponse(
        backup_path,
        filename=backup_path.name,
        media_type="application/octet-stream",
    )
