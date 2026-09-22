"""Durable, transactionally captured document copies; remote outages never lose a queue item."""
import asyncio
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import re
import uuid

from sqlalchemy import event, or_, update

from models import CloudAsset, CloudRun, SiteDocument, SitePlan, PurchaseOrder
from services.sharepoint_client import CloudError, GraphClient, SharePointConfig


def enqueue_connection(connection, kind, source_id, filename, data, content_type="application/octet-stream", site_id=None):
    if not data:
        raise ValueError("Empty documents cannot be archived")
    digest = hashlib.sha256(data).hexdigest()
    key = f"{kind}:{source_id}:{digest}"
    values = dict(source_key=key, kind=kind, source_id=str(source_id), site_id=site_id,
        filename=str(filename)[:300], content_type=content_type[:150], sha256=digest,
        size_bytes=len(data), payload=data, created_at=datetime.utcnow(), status="pending", attempts=0)
    if connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    connection.execute(insert(CloudAsset.__table__).values(**values).on_conflict_do_nothing(index_elements=["source_key"]))
    return key


def enqueue(db, kind, source_id, filename, data, content_type="application/octet-stream", site_id=None):
    return enqueue_connection(db.connection(), kind, source_id, filename, data, content_type, site_id)


def _document_saved(mapper, connection, target):
    if target.data:
        enqueue_connection(connection, "document", target.id, target.filename, target.data,
                           target.content_type or "application/octet-stream", target.site_id)


def _plan_saved(mapper, connection, target):
    enqueue_connection(connection, "plan", target.id, target.filename, target.pdf_data, "application/pdf", target.site_id)
    if target.preview_data:
        enqueue_connection(connection, "plan_preview", target.id, "preview.png", target.preview_data, "image/png", target.site_id)


def install_capture_hooks():
    # Mapper callbacks use the same connection: rollback also rolls back the copy.
    for model, callback in [(SiteDocument, _document_saved), (SitePlan, _plan_saved)]:
        if not event.contains(model, "after_insert", callback):
            event.listen(model, "after_insert", callback)
        if not event.contains(model, "before_delete", callback):
            event.listen(model, "before_delete", callback)


def legacy_invoice_path(value, root=None):
    root = (root or Path("static/uploads/invoices")).resolve()
    normalized = str(value or "").replace("\\", "/")
    if not normalized.startswith("uploads/invoices/"):
        raise CloudError("invalid_legacy_path")
    name = normalized.removeprefix("uploads/invoices/")
    candidate = (root / name).resolve()
    if not name or Path(name).name != name or candidate.parent != root:
        raise CloudError("invalid_legacy_path")
    return candidate


def prepare_existing(db, invoice_root=None):
    """Idempotent inventory. Originals stay untouched; legacy invoice pointers become durable."""
    result = {"documents": 0, "plans": 0, "invoices": 0, "missing": [], "missing_count": 0}
    for doc in db.query(SiteDocument).yield_per(1):
        if doc.data:
            enqueue(db, "document", doc.id, doc.filename, doc.data, doc.content_type or "application/octet-stream", doc.site_id)
            result["documents"] += 1
        else:
            result["missing_count"] += 1
            if len(result["missing"]) < 100:
                result["missing"].append(f"document:{doc.id}")
    for plan in db.query(SitePlan).yield_per(1):
        _plan_saved(None, db.connection(), plan)
        result["plans"] += 1
    for order in db.query(PurchaseOrder).filter(PurchaseOrder.file_invoice.isnot(None)).yield_per(25):
        if order.file_invoice.startswith("cloud:"):
            if db.query(CloudAsset.id).filter_by(source_key=order.file_invoice[6:], kind="invoice", source_id=str(order.id)).first():
                result["invoices"] += 1
                continue
            result["missing_count"] += 1
            if len(result["missing"]) < 100:
                result["missing"].append(f"invoice:{order.id}")
            continue
        try:
            path = legacy_invoice_path(order.file_invoice, invoice_root)
            if path.stat().st_size > 64 * 1024 * 1024:
                raise CloudError("legacy_file_too_large")
            content = path.read_bytes()
            if not content:
                raise CloudError("empty_file")
            key = enqueue(db, "invoice", order.id, path.name, content, site_id=order.site_id)
            order.file_invoice = "cloud:" + key
            result["invoices"] += 1
        except (OSError, CloudError):
            result["missing_count"] += 1
            if len(result["missing"]) < 100:
                result["missing"].append(f"invoice:{order.id}")
    db.add(CloudRun(kind="inventory", status="attention" if result["missing_count"] else "complete",
        finished_at=datetime.utcnow(), details=json.dumps(result)))
    db.commit()
    return result


def remote_location(asset):
    parts = ["Gestionale", "Cantieri", f"cantiere-{asset.site_id}"] if asset.site_id else ["Gestionale", "Acquisti"]
    parts.append({"document": "Documenti", "plan": "Piante-originali", "plan_preview": "Piante-anteprime",
        "fiche_pdf": "Fiches", "dossier_pdf": "Dossier", "invoice": "Fatture"}.get(asset.kind, "Esportazioni"))
    original = Path(asset.filename.replace("\\", "/")).name
    extension = re.sub(r"[^a-zA-Z0-9.]", "", Path(original).suffix)[:12]
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(original).stem).strip(".-")[:58] or "documento"
    name = stem + extension
    return parts, f"{asset.source_id}-{asset.sha256}-{name}"


def sync_batch(factory, config=None, client=None, limit=3):
    config = config or SharePointConfig.from_env()
    if not config.enabled:
        return {"verified": 0, "failed": 0, "paused": True}
    graph = client or GraphClient(config)
    result = {"verified": 0, "failed": 0, "paused": False}
    try:
        drive = graph.check_destination()
        for _ in range(limit):
            now = datetime.utcnow()
            token = uuid.uuid4().hex
            eligible = ((CloudAsset.status != "verified") &
                or_(CloudAsset.next_attempt.is_(None), CloudAsset.next_attempt <= now) &
                or_(CloudAsset.lease_until.is_(None), CloudAsset.lease_until < now))
            with factory() as db:
                candidate = db.query(CloudAsset.id).filter(eligible).order_by(CloudAsset.id).first()
                if not candidate:
                    break
                claimed = db.execute(update(CloudAsset).where(CloudAsset.id == candidate.id, eligible).values(
                    status="sending", lease_token=token, lease_until=now + timedelta(minutes=30), attempts=CloudAsset.attempts + 1))
                db.commit()
                if not claimed.rowcount:
                    continue
                asset = db.get(CloudAsset, candidate.id)
                parts, filename = remote_location(asset)
                try:
                    if hashlib.sha256(asset.payload).hexdigest() != asset.sha256:
                        raise CloudError("local_integrity_failed")
                    item_id = graph.upload(drive, parts, filename, io.BytesIO(asset.payload), asset.size_bytes, asset.sha256)
                    values = dict(status="verified", drive_id=drive, item_id=item_id, remote_path="/".join(parts + [filename]),
                                  verified_at=datetime.utcnow(), error_code=None, next_attempt=None)
                    result["verified"] += 1
                except Exception as exc:
                    code = exc.code if isinstance(exc, CloudError) else "unexpected_error"
                    delay = max(getattr(exc, "retry_after", 60), min(60 * 2 ** min(asset.attempts, 10), 86400))
                    values = dict(status="error", error_code=code, next_attempt=datetime.utcnow() + timedelta(seconds=delay))
                    result["failed"] += 1
                db.execute(update(CloudAsset).where(CloudAsset.id == asset.id, CloudAsset.lease_token == token).values(
                    **values, lease_token=None, lease_until=None))
                db.commit()
    finally:
        if client is None:
            graph.close()
    return result


async def background_sync(factory):
    """Opt-in worker; persistent leases allow safe restart and multiple web workers."""
    def initial_inventory():
        with factory() as db:
            if not db.query(CloudRun.id).filter_by(kind="inventory", status="complete").first():
                prepare_existing(db)
    try:
        await asyncio.to_thread(initial_inventory)
    except Exception:
        with factory() as db:
            db.add(CloudRun(kind="inventory", status="error", details='{"error":"inventory_failed"}', finished_at=datetime.utcnow()))
            db.commit()
    while True:
        config = SharePointConfig.from_env()
        if config.enabled:
            try:
                await asyncio.to_thread(sync_batch, factory, config)
            except Exception as exc:
                # Persist only a safe code, never an HTTP response or credentials.
                code = exc.code if isinstance(exc, CloudError) else "unexpected_error"
                with factory() as db:
                    last = db.query(CloudRun).filter_by(kind="sync").order_by(CloudRun.id.desc()).first()
                    if not last or last.details != code or last.created_at < datetime.utcnow() - timedelta(hours=1):
                        db.add(CloudRun(kind="sync", status="error", details=code, finished_at=datetime.utcnow()))
                        db.commit()
        await asyncio.sleep(60)
