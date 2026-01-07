from __future__ import annotations

import logging
import os
import sys
from typing import Optional


def _parse_level(value: Optional[str], default: int) -> int:
    if not value:
        return default
    level = logging.getLevelName(value.upper())
    return level if isinstance(level, int) else default


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    console_level = _parse_level(os.getenv("LOG_LEVEL"), logging.INFO)
    file_level = _parse_level(os.getenv("LOG_FILE_LEVEL"), logging.WARNING)
    log_file = os.getenv("LOG_FILE")

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    root_logger.setLevel(min(console_level, file_level))
