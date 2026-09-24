"""Run from the repository root: python -m scripts.sharepoint_sync [--backup]."""
import argparse
import json
from database import SessionLocal
from services.cloud_archive import prepare_existing, sync_batch
from services.cloud_backup import send_backup
from services.archive_reorganization import reorganize_batch
from services.sharepoint_client import CloudError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", action="store_true", help="Send native snapshot to the approved restricted library")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    try:
        with SessionLocal() as db:
            inventory = prepare_existing(db)
        print(json.dumps({"inventory": inventory}))
        sync_result = sync_batch(SessionLocal, limit=max(1, min(args.limit, 1000)))
        print(json.dumps({"sync": sync_result}))
        reorder_result = reorganize_batch(SessionLocal, limit=max(1, min(args.limit, 1000)))
        print(json.dumps({"reorganization": reorder_result}))
        if args.backup:
            result = send_backup(SessionLocal)
            print(json.dumps({"backup": "verified", "filename": result["filename"]}))
        if inventory["missing_count"]:
            raise CloudError("missing_sources")
        if reorder_result["failed"]:
            raise CloudError("reorganization_failed")
        if sync_result["failed"] or sync_result["paused"]:
            raise CloudError("sync_failed" if sync_result["failed"] else "sync_disabled")
    except CloudError as exc:
        print(json.dumps({"error": exc.code}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
