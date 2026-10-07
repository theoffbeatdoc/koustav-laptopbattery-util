"""Logging setup (rotating file log under %LOCALAPPDATA%)."""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from .paths import ensure_app_dir, log_path

_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
MAX_BYTES = 512 * 1024
BACKUPS = 3


def setup_logging(*, debug: bool = False) -> None:
    """Initial setup. Uses a plain FileHandler so short-lived helper processes
    (toast actions, --install...) never try to rotate a file the tray instance
    has open. The tray instance calls :func:`upgrade_to_rotating`."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter(_FORMAT)
    try:
        ensure_app_dir()
        fh = logging.FileHandler(log_path(), encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    if sys.stderr is not None:  # absent in a --windowed EXE
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    def _excepthook(exc_type, exc, tb):
        logging.getLogger("unhandled").critical("Unhandled exception", exc_info=(exc_type, exc, tb))

    def _thread_hook(args: threading.ExceptHookArgs):
        logging.getLogger("unhandled").critical(
            "Unhandled exception in thread %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook


def upgrade_to_rotating() -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        if type(h) is logging.FileHandler:
            root.removeHandler(h)
            h.close()
    try:
        rh = RotatingFileHandler(log_path(), maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                 encoding="utf-8")
        rh.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(rh)
    except OSError:
        logging.getLogger(__name__).exception("Could not enable rotating log")
