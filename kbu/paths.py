"""Filesystem locations and the command used to (re)launch this program."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .constants import APP_DIR_NAME, APP_NAME


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))


def app_dir() -> Path:
    return _local_appdata() / APP_DIR_NAME


def config_path() -> Path:
    return app_dir() / "config.json"


def log_path() -> Path:
    return app_dir() / "app.log"


def icon_path() -> Path:
    return app_dir() / "icon.ico"


def ensure_app_dir() -> Path:
    d = app_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def startup_shortcut_path() -> Path:
    return (_appdata() / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            / "Startup" / f"{APP_NAME}.lnk")


def start_menu_shortcut_path() -> Path:
    return (_appdata() / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            / f"{APP_NAME}.lnk")


def launch_command() -> tuple[str, list[str]]:
    """Return (executable, leading_args) that start this program.

    Frozen: the EXE itself. Development: pythonw.exe (no console) + app.py.
    """
    if is_frozen():
        return sys.executable, []
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    script = Path(__file__).resolve().parent.parent / "app.py"
    return str(pythonw if pythonw.exists() else exe), [str(script)]
