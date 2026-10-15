"""Rotating diagnostic log and crash capture."""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import state_home
from .constants import APP_NAME

LOGGER = logging.getLogger("hackerterminal")


def log_path() -> Path:
    return state_home() / APP_NAME / f"{APP_NAME}.log"


def setup_logging(debug: bool = False) -> Path | None:
    """Log to a small rotating file; never let logging stop the terminal."""
    level = logging.DEBUG if debug else logging.INFO
    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        handler.close()
    LOGGER.setLevel(level)
    LOGGER.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if debug else logging.WARNING)
    console.setFormatter(formatter)
    LOGGER.addHandler(console)
    path: Path | None = log_path()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=256 * 1024, backupCount=2, encoding="utf-8")
        handler.setFormatter(formatter)
        handler.setLevel(level)
        LOGGER.addHandler(handler)
        path.chmod(0o600)
    except OSError:
        path = None

    def excepthook(kind, value, trace) -> None:
        # PyGObject reports exceptions raised inside GTK callbacks here; the
        # main loop keeps running, so record them instead of losing them.
        LOGGER.error("erro não tratado:\n%s", "".join(traceback.format_exception(kind, value, trace)))

    sys.excepthook = excepthook
    return path
