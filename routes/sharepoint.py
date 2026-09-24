from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import time
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import SECRET_KEY, get_current_active_user_html
from audit_utils import log_audit_event
from database import get_db
from models import CloudAsset, CloudRun, User
from permissions import has_perm
from services.cloud_archive import prepare_existing
from services.archive_context import archive_context
from services.archive_layout import legacy_filter
from services.archive_lifecycle import ACTIVE, TRASH, change_state, selected_assets, purge_selected, invoice_in_use
from services.sharepoint_client import SharePointConfig, GraphClient, CloudError
from template_context import register_manager_badges, render_template

router = APIRouter(prefix="/admin/sharepoint", tags=["SharePoint"])
templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)


def admin(user):
    if not has_perm(user, "settings.manage"):
        raise HTTPException(403, "Permessi insufficienti")


def is_owner(user):
    email = os.getenv("CLOUD_ARCHIVE_OWNER_EMAIL", "").strip().casefold()
    return bool(email and user.email.casefold() == email and has_perm(user, "settings.manage"))


def csrf_token(user):
    value = f"{user.id}:{int(time.time())}:{secrets.token_hex(12)}"
    signature = hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()
    return value + ":" + signature


def validate_post(request, user, csrf):
    admin(user)
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(403, "Origine non valida")
    try:
        uid, stamp, nonce, signature = csrf.split(":")
        expected = hmac.new(SECRET_KEY.encode(), f"{uid}:{stamp}:{nonce}".encode(), hashlib.sha256).hexdigest()
        valid = int(uid) == user.id and 0 <= time.time() - int(stamp) <= 7200 and hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(403, "Ricaricare la pagina prima di riprovare")


def fingerprint(config):
    return hashlib.sha256("|".join([config.tenant, config.client_id, config.site_id, config.drive_id, config.hostname]).encode()).hexdigest()


@router.get("", name="admin_sharepoint")
def page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    admin(user)
    config = SharePointConfig.from_env()
    counts = dict(db.query(CloudAsset.status, func.count(CloudAsset.id)).group_by(CloudAsset.status).all())
    runs = db.query(CloudRun).order_by(CloudRun.id.desc()).limit(12).all()
    connection = db.query(CloudRun).filter_by(kind="connection").order_by(CloudRun.id.desc()).first()
    connected = bool(connection and connection.status == "readable" and connection.details == fingerprint(config))
    inventory = db.query(CloudRun).filter(CloudRun.kind == "inventory", CloudRun.status.in_(["complete", "attention"])).order_by(CloudRun.id.desc()).first()
    inventory_data = json.loads(inventory.details) if inventory and inventory.details else None
    owner_configured = bool(os.getenv("CLOUD_ARCHIVE_OWNER_EMAIL", "").strip())
    last_backup = db.query(CloudRun).filter_by(kind="backup", status="verified").order_by(CloudRun.id.desc()).first()
    view = request.query_params.get("view", "active")
    if view not in ("active", "excluded", "trash"):
        view = "active"
    if view == "trash" and not is_owner(user):
        raise HTTPException(403, "Cestino riservato al titolare configurato")
    try:
        page_number = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page_number = 1
    query = db.query(CloudAsset).filter(CloudAsset.status.in_(
        ACTIVE if view == "active" else TRASH if view == "trash" else ("excluded",)))
    total = query.count()
    page_number = min(page_number, max(1, (total + 39) // 40))
    assets = query.order_by(CloudAsset.id.desc()).offset((page_number - 1) * 40).limit(40).all()
    return render_template(templates, request, "admin/sharepoint.html", {
        "config_missing": config.missing(), "sync_enabled": config.enabled,
        "connected": connected, "counts": counts, "runs": runs,
        "reorder_pending": db.query(CloudAsset.id).filter(CloudAsset.status == "verified", legacy_filter()).count(),
        "reorder_failed": db.query(CloudAsset.id).filter(CloudAsset.status == "verified", legacy_filter(),
                                                       CloudAsset.error_code.startswith("reorder_")).count(),
        "assets": assets, "asset_context": archive_context(db, assets),
        "view": view, "page_number": page_number, "total": total,
        "has_next": page_number * 40 < total,
        "notice": request.query_params.get("notice", ""),
        "error": request.query_params.get("error", ""),
        "inventory": inventory_data, "csrf": csrf_token(user), "owner": is_owner(user),
        "owner_configured": owner_configured,
        "last_backup": last_backup,
        "backup_destination": bool(config.backup_site_id and config.backup_drive_id and config.backup_access_confirmed
                                   and config.backup_drive_id != config.drive_id),
        "backup_tool": db.get_bind().dialect.name == "sqlite" or bool(shutil.which("pg_dump")),
        "archive_bytes": db.query(func.coalesce(func.sum(CloudAsset.size_bytes), 0)).scalar(),
    }, db, user)


@router.post("/archivio/azioni", name="admin_cloud_asset_action")
def archive_action(request: Request, csrf: str = Form(""), action: str = Form(""),
                   asset_ids: list[int] = Form([]), confirmation: str = Form(""),
                   view: str = Form("active"), db: Session = Depends(get_db),
                   user: User = Depends(get_current_active_user_html)):
    validate_post(request, user, csrf)
    if not is_owner(user):
        raise HTTPException(403, "Archivio riservato al titolare configurato")
    view = view if view in ("active", "excluded", "trash") else "active"
    try:
        if action == "purge_review":
            assets = selected_assets(db, asset_ids)
            if any(a.status not in TRASH for a in assets):
                raise CloudError("selection_changed")
            return render_template(templates, request, "admin/sharepoint_purge.html", {
                "assets": assets, "csrf": csrf_token(user), "asset_context": archive_context(db, assets),
                "invoice_blocked": any(invoice_in_use(db, a) for a in assets),
            }, db, user)
        if action == "purge":
            if confirmation.strip() not in ("ELIMINA DEFINITIVAMENTE", "SUPPRIMER DÉFINITIVEMENT"):
                raise CloudError("confirmation_required")
            result = purge_selected(db, user, asset_ids)
            notice = "purge_partial" if result["failed"] else "purged"
            view = "trash"
        else:
            change_state(db, user, asset_ids, action)
            notice = action
        return RedirectResponse(f"/admin/sharepoint?view={view}&notice={notice}#archive", 303)
    except CloudError as exc:
        db.rollback()
        return RedirectResponse(f"/admin/sharepoint?view={view}&error={quote(exc.code, safe='')}#archive", 303)


@router.post("/prepara", name="admin_sharepoint_prepare")
def prepare(request: Request, csrf: str = Form(""), db: Session = Depends(get_db),
            user: User = Depends(get_current_active_user_html)):
    validate_post(request, user, csrf)
    result = prepare_existing(db)
    log_audit_event(db, user, "CLOUD_INVENTORY", "cloud", extra_data={"missing_count": result["missing_count"]})
    db.commit()
    return RedirectResponse("/admin/sharepoint", 303)


@router.post("/verifica", name="admin_sharepoint_check")
def check(request: Request, csrf: str = Form(""), db: Session = Depends(get_db),
          user: User = Depends(get_current_active_user_html)):
    validate_post(request, user, csrf)
    config = SharePointConfig.from_env()
    graph = None
    try:
        graph = GraphClient(config)
        graph.check_destination()
        status, details = "readable", fingerprint(config)
    except Exception as exc:
        status, details = "error", exc.code if isinstance(exc, CloudError) else "connection_failed"
    finally:
        if graph:
            graph.close()
    db.add(CloudRun(kind="connection", status=status, details=details, finished_at=datetime.utcnow()))
    log_audit_event(db, user, "CLOUD_CONNECTION_CHECK", "cloud", extra_data={"status": status})
    db.commit()
    return RedirectResponse("/admin/sharepoint", 303)


@router.post("/riprova", name="admin_sharepoint_retry")
def retry(request: Request, csrf: str = Form(""), db: Session = Depends(get_db),
          user: User = Depends(get_current_active_user_html)):
    validate_post(request, user, csrf)
    count = db.query(CloudAsset).filter_by(status="error").update({CloudAsset.next_attempt: None, CloudAsset.status: "pending"})
    count += db.query(CloudAsset).filter(CloudAsset.status == "verified", legacy_filter(),
        CloudAsset.error_code.startswith("reorder_"), CloudAsset.lease_token.is_(None)).update({CloudAsset.next_attempt: None})
    log_audit_event(db, user, "CLOUD_RETRY", "cloud", extra_data={"count": count})
    db.commit()
    return RedirectResponse("/admin/sharepoint", 303)


@router.get("/guida", name="admin_sharepoint_guide")
def guide(user: User = Depends(get_current_active_user_html)):
    admin(user)
    content = (Path(__file__).resolve().parents[1] / "docs/sharepoint.md").read_bytes()
    return Response(content, media_type="text/markdown; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="Lenta-France-SharePoint.md"', "Cache-Control": "no-store"})


@router.get("/archivio/{asset_id}", name="admin_cloud_asset_download")
def download(asset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    if not is_owner(user):
        raise HTTPException(403, "Archivio riservato al titolare configurato")
    asset = db.get(CloudAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Documento non trovato")
    if asset.status == "deleted":
        raise HTTPException(410, "Copia eliminata definitivamente")
    if hashlib.sha256(asset.payload).hexdigest() != asset.sha256:
        raise HTTPException(409, "Verifica integrità non riuscita")
    log_audit_event(db, user, "CLOUD_ARCHIVE_DOWNLOAD", "cloud_asset", asset.id)
    content, filename = asset.payload, asset.filename
    db.commit()
    return Response(content, media_type="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
