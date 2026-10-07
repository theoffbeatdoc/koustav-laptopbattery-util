"""Shared constants and the toast-action protocol definition."""
from __future__ import annotations

import os
import re
from enum import Enum
from urllib.parse import urlparse

APP_NAME = "Koustav Laptop Battery Util"
PACKAGE_NAME = "koustav-laptopbattery-util"
EXE_NAME = f"{PACKAGE_NAME}.exe"
APP_DIR_NAME = "KoustavLaptopBatteryUtil"

# Stable AppUserModelID: ties toasts, the Start Menu shortcut and the registry
# registration together. Never change it once installed.
AUMID = "Koustav.KoustavLaptopBatteryUtil"

PROTOCOL = "koustav-laptopbattery"
MUTEX_NAME = r"Local\KoustavLaptopBatteryUtil.SingleInstance"

RENOTIFY_SECONDS = 5 * 60
OVERRIDE_TARGET = 99
TOAST_GROUP = "battery"


def pipe_name() -> str:
    """Per-user named pipe used for second-instance -> first-instance messages."""
    user = re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get("USERNAME", "user"))
    return rf"\\.\pipe\KoustavLaptopBatteryUtil.{user}"


class Action(str, Enum):
    RENOTIFY_UPPER = "renotify_upper"
    CHARGE_99 = "charge99"
    IGNORE_UPPER = "ignore_upper"
    RENOTIFY_LOWER = "renotify_lower"
    IGNORE_LOWER = "ignore_lower"


def action_uri(action: Action) -> str:
    return f"{PROTOCOL}://action/{action.value}"


def parse_action_uri(uri: str) -> Action | None:
    """Parse ``koustav-laptopbattery://action/<name>``; None if invalid.

    Only whitelisted action names are accepted.
    """
    try:
        parsed = urlparse(uri.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() != PROTOCOL or parsed.netloc.lower() != "action":
        return None
    try:
        return Action(parsed.path.strip("/").lower())
    except ValueError:
        return None
