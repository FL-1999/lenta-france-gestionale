from __future__ import annotations

import sys
from pathlib import Path

from backup_utils import create_database_backup


def main() -> int:
    backup_path: Path = create_database_backup()
    print(f"Backup creato: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
