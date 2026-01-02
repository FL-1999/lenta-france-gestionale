#!/usr/bin/env python3
import re
import subprocess
import sys
from pathlib import Path

MARKER_PATTERN = re.compile(r"^(<{7}|={7}|>{7})")


def iter_tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=True,
    )
    files = [Path(path) for path in result.stdout.split("\0") if path]
    return files


def check_file(path: Path) -> list[tuple[int, str]]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    hits: list[tuple[int, str]] = []
    for index, line in enumerate(content.splitlines(), start=1):
        if MARKER_PATTERN.match(line):
            hits.append((index, line))
    return hits


def main() -> int:
    violations: list[str] = []
    for path in iter_tracked_files():
        if not path.is_file():
            continue
        hits = check_file(path)
        for line_no, line in hits:
            violations.append(f"{path}:{line_no}: {line}")

    if violations:
        print("Git conflict markers detected:")
        print("\n".join(violations))
        return 1

    print("No Git conflict markers found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
