from __future__ import annotations

import base64
import datetime as _dt
import decimal
import json
import enum as _enum

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from audit_utils import log_audit_event
from auth import get_current_active_user_html
from backup_utils import create_database_backup, get_backup_path, list_backups
from database import get_db, engine, Base
from models import User
from template_context import register_manager_badges, render_template
from permissions import has_perm

from datetime import datetime


def _json_default(value):
    """Serializza i tipi non-JSON per l'export completo del database."""
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes_b64__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (_dt.date, _dt.datetime, _dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, _enum.Enum):
        return value.value
    return str(value)


def _export_all_tables() -> dict:
    """Esporta tutte le righe di tutte le tabelle in un dizionario JSON-serializzabile.
    Portabile: funziona sia su SQLite sia su PostgreSQL."""
    tables = {}
    seen = set()
    with engine.connect() as conn:
        for metadata in (Base.metadata, SQLModel.metadata):
            for table in metadata.sorted_tables:
                if table.name in seen:
                    continue
                seen.add(table.name)
                try:
                    rows = conn.execute(table.select()).mappings().all()
                except Exception as exc:  # noqa: BLE001
                    tables[table.name] = {"__error__": str(exc)}
                    continue
                tables[table.name] = [dict(r) for r in rows]
    return {
        "exported_at": datetime.utcnow().isoformat(),
        "database_dialect": engine.dialect.name,
        "tables": tables,
    }


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
    from database import is_sqlite
    backups = list_backups() if is_sqlite() else []
    return render_template(
        templates,
        request,
        "admin/backup_export.html",
        {
            "backups": backups,
            "is_sqlite": is_sqlite(),
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
    "/admin/backup-export/json",
    name="admin_backup_export_json",
)
def backup_export_json(
    current_user: User = Depends(get_current_active_user_html),
):
    """Export completo del database in JSON (portabile, funziona su Postgres).
    File di backup scaricabile manualmente."""
    _ensure_admin(current_user)
    payload = _export_all_tables()
    body = json.dumps(payload, default=_json_default, ensure_ascii=False, indent=1)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"lenta_france_export_{stamp}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, max-age=0",
        },
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
