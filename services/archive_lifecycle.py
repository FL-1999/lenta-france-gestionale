"""Owner-driven archive lifecycle. No automatic purge, no business-record deletion."""
from datetime import datetime, timedelta
import uuid

from sqlalchemy import or_, update

from audit_utils import log_audit_event
from models import CloudAsset, PurchaseOrder
from services.sharepoint_client import CloudError, GraphClient, SharePointConfig

ACTIVE = ("pending", "error", "sending", "verified")
TRASH = ("trashed", "purge_error", "purging")
TRANSITIONS = {
    "exclude": (ACTIVE, "excluded"),
    "include": (("excluded",), "pending"),
    "trash": (ACTIVE + ("excluded",), "trashed"),
    # Restoring never starts a transfer. The owner explicitly includes it later.
    "restore": (("trashed", "purge_error"), "excluded"),
}


def selected_assets(db, ids):
    ids = sorted(set(ids))
    if not ids or len(ids) > 40:
        raise CloudError("invalid_selection")
    rows = db.query(CloudAsset).filter(CloudAsset.id.in_(ids)).order_by(CloudAsset.id).all()
    if len(rows) != len(ids) or any(a.status == "deleted" for a in rows):
        raise CloudError("selection_changed")
    return rows


def change_state(db, user, ids, action):
    if action not in TRANSITIONS:
        raise CloudError("invalid_action")
    rows = selected_assets(db, ids)
    allowed, target = TRANSITIONS[action]
    for asset in rows:
        # Also block expired upload leases: let the sync worker reconcile them.
        result = db.execute(update(CloudAsset).where(
            CloudAsset.id == asset.id, CloudAsset.status.in_(allowed),
            CloudAsset.lease_token.is_(None),
        ).values(status=target, next_attempt=None, error_code=None))
        if result.rowcount != 1:
            db.rollback()
            raise CloudError("selection_busy_or_changed")
        log_audit_event(db, user, "CLOUD_ARCHIVE_" + action.upper(), "cloud_asset", asset.id)
    db.commit()
    return len(rows)


def invoice_in_use(db, asset):
    # For current invoices the archive payload IS the live original.
    return bool(db.query(PurchaseOrder.id).filter(
        PurchaseOrder.file_invoice == "cloud:" + asset.source_key).first())


def purge_selected(db, user, ids, config=None, client=None):
    """Remote first, local second. Failures keep the recovery payload in trash.

    Tombstones retain source_key so inventory/capture hooks cannot resurrect the
    same archived version. Historical backups and source documents are separate.
    """
    rows = selected_assets(db, ids)
    now = datetime.utcnow()
    for asset in rows:
        if asset.status not in TRASH or (asset.lease_token and (
            asset.status != "purging" or not asset.lease_until or asset.lease_until > now)):
            raise CloudError("selection_busy_or_changed")
        if invoice_in_use(db, asset):
            raise CloudError("invoice_still_in_use")
    result = {"deleted": 0, "failed": 0}
    graph = client
    config = config or SharePointConfig.from_env()
    try:
        for asset in rows:
            asset_id = asset.id
            token = uuid.uuid4().hex
            claimed = db.execute(update(CloudAsset).where(
                CloudAsset.id == asset_id, CloudAsset.status.in_(TRASH),
                or_(CloudAsset.lease_token.is_(None),
                    (CloudAsset.status == "purging") & (CloudAsset.lease_until < datetime.utcnow())),
            ).values(status="purging", lease_token=token,
                     lease_until=datetime.utcnow() + timedelta(minutes=30), error_code=None))
            if claimed.rowcount != 1:
                db.rollback()
                result["failed"] += 1
                continue
            log_audit_event(db, user, "CLOUD_ARCHIVE_PURGE_REQUEST", "cloud_asset", asset_id)
            db.commit()
            db.refresh(asset)
            try:
                if invoice_in_use(db, asset):
                    raise CloudError("invoice_still_in_use")
                if asset.item_id or asset.drive_id or asset.attempts:
                    if not asset.drive_id or not (asset.item_id or asset.remote_path):
                        raise CloudError("archive_destination_unknown")
                    if graph is None:
                        graph = GraphClient(config)
                    # Refuse a changed library rather than deleting in a new one.
                    if graph.check_destination() != asset.drive_id:
                        raise CloudError("destination_mismatch")
                    graph.purge_archive_copy(asset.drive_id, asset.item_id, asset.remote_path,
                                             asset.sha256, asset.size_bytes)
                values = dict(status="deleted", payload=b"", size_bytes=0,
                              item_id=None, drive_id=None, remote_path=None, verified_at=None,
                              next_attempt=None, error_code=None)
                result["deleted"] += 1
                event_name = "CLOUD_ARCHIVE_PURGED"
            except Exception as exc:
                values = dict(status="purge_error", error_code=(
                    exc.code if isinstance(exc, CloudError) else "remote_delete_failed"))
                result["failed"] += 1
                event_name = "CLOUD_ARCHIVE_PURGE_FAILED"
            updated = db.execute(update(CloudAsset).where(
                CloudAsset.id == asset_id, CloudAsset.lease_token == token,
            ).values(**values, lease_token=None, lease_until=None))
            if updated.rowcount != 1:
                db.rollback()
                raise CloudError("selection_busy_or_changed")
            log_audit_event(db, user, event_name, "cloud_asset", asset_id,
                            extra_data={"error": values.get("error_code")})
            db.commit()
    finally:
        if graph is not None and client is None:
            graph.close()
    return result
