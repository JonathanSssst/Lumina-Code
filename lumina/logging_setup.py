from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from lumina.config import migrate_legacy_workspace_data, workspace_data_dir

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 3


def setup_logging(workspace: Path, level: int = logging.INFO) -> Path:
    """Persist logging to <user data>/<workspace>/lumina.log (rotating).

    Safe to call repeatedly. Also migrates any legacy .lumina folder first so
    old data is never orphaned.
    """
    migrate_legacy_workspace_data(workspace)
    log_dir = workspace_data_dir(workspace)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "lumina.log"

    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", None) == str(log_path):
            return log_path

    handler = RotatingFileHandler(
        log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUPS,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.setLevel(level)
    root.addHandler(handler)
    return log_path
