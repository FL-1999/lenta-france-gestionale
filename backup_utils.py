from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from database import DATABASE_URL


@dataclass(frozen=True)
class BackupInfo:
    name: str
    path: Path
    size_bytes: int
    created_at: datetime


def _resolve_backup_dir() -> Path:
    backup_dir = os.getenv("BACKUP_DIR", "backups")
    path = Path(backup_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_sqlite_path(db_url: str) -> Path:
    url = make_url(db_url)
    if url.drivername != "sqlite":
        raise ValueError("Database non supportato per backup locale.")
    if url.database is None:
        raise ValueError("Percorso del database SQLite non valido.")
    return Path(url.database).expanduser()


def create_database_backup() -> Path:
    db_url = os.getenv("DATABASE_URL", DATABASE_URL)
    db_path = _resolve_sqlite_path(db_url)
    backup_dir = _resolve_backup_dir()
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.sqlite3"
    backup_path = backup_dir / backup_name

    src_conn = sqlite3.connect(db_path)
    dst_conn = sqlite3.connect(backup_path)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    return backup_path


def list_backups() -> list[BackupInfo]:
    backup_dir = _resolve_backup_dir()
    backups: list[BackupInfo] = []
    for path in backup_dir.glob("backup_*.sqlite3"):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        backups.append(
            BackupInfo(
                name=path.name,
                path=path,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime),
            )
        )
    backups.sort(key=lambda item: item.created_at, reverse=True)
    return backups


def get_backup_path(filename: str) -> Path:
    backup_dir = _resolve_backup_dir().resolve()
    safe_name = Path(filename).name
    candidate = (backup_dir / safe_name).resolve()
    if backup_dir not in candidate.parents and candidate != backup_dir:
        raise ValueError("Percorso backup non valido.")
    return candidate
