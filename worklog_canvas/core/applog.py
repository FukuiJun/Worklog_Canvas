"""ログ（仕様8章）: %APPDATA%/WorklogCanvas/app.log。1MBで世代交代し、3世代（現行＋過去2つ）を保持する。

予定の件名などの個人の予定はログに出さない。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME = "worklog_canvas"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 2  # app.log + app.log.1 + app.log.2 = 3世代


def setup(app_dir: Path) -> logging.Logger:
    logger = logging.getLogger(LOG_NAME)
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return logger
    logger.setLevel(logging.INFO)
    try:
        app_dir.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(app_dir / "app.log", maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                                encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    except OSError:
        logger.addHandler(logging.NullHandler())
    return logger


def get() -> logging.Logger:
    return logging.getLogger(LOG_NAME)
