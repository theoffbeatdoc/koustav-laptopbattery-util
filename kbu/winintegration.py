"""Windows integration: protocol handler, AppUserModelID, shortcuts, startup.

Everything lives under HKCU / the user's profile - no administrator rights needed.
pywin32 COM modules are imported lazily so that merely importing this module does not
initialise COM on the calling thread.
"""
from __future__ import annotations

import logging
import subprocess
import winreg
from pathlib import Path

from . import icon as icon_mod
from .config import Config
from .constants import APP_NAME, AUMID, PROTOCOL
from .paths import (app_dir, ensure_app_dir, icon_path, is_frozen, launch_command,
                    start_menu_shortcut_path, startup_shortcut_path)

log = logging.getLogger(__name__)

_PROTO_KEY = rf"Software\Classes\{PROTOCOL}"
_AUMID_KEY = rf"Software\Classes\AppUserModelId\{AUMID}"


# ---------- registry helpers ----------
def _set(key_path: str, name: str, value: str) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def _get(key_path: str, name: str = "") -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except FileNotFoundError:
        return None


def _delete_tree(subkey: str) -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return False
    with key:
        while True:
            try:
                child = winreg.EnumKey(key, 0)
            except OSError:
                break
            _delete_tree(subkey + "\\" + child)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
    return True


# ---------- protocol ----------
def protocol_command() -> str:
    exe, args = launch_command()
    parts = [f'"{exe}"'] + [f'"{a}"' for a in args] + ['"%1"']
    return " ".join(parts)


def register_protocol() -> None:
    _set(_PROTO_KEY, "", f"URL:{APP_NAME}")
    _set(_PROTO_KEY, "URL Protocol", "")
    _set(_PROTO_KEY + r"\DefaultIcon", "", str(icon_path()))
    _set(_PROTO_KEY + r"\shell\open\command", "", protocol_command())
    log.info("Registered protocol %s:// -> %s", PROTOCOL, protocol_command())


def unregister_protocol() -> None:
    if _delete_tree(_PROTO_KEY):
        log.info("Removed protocol registration")


def is_protocol_current() -> bool:
    return _get(_PROTO_KEY + r"\shell\open\command") == protocol_command()


# ---------- AppUserModelID ----------
def register_aumid() -> None:
    _set(_AUMID_KEY, "DisplayName", APP_NAME)
    _set(_AUMID_KEY, "IconUri", str(icon_path()))
    _set(_AUMID_KEY, "IconBackgroundColor", "FF262A30")
    log.info("Registered AppUserModelID %s", AUMID)


def unregister_aumid() -> None:
    if _delete_tree(_AUMID_KEY):
        log.info("Removed AppUserModelID registration")


# ---------- shortcuts ----------
def _write_shortcut(lnk: Path, target: str, args: list[str], icon: Path | None,
                    description: str, aumid: str | None) -> None:
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell
    import pythoncom

    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)
    link.SetPath(target)
    link.SetArguments(subprocess.list2cmdline(args))
    link.SetWorkingDirectory(str(Path(target).parent))
    link.SetDescription(description)
    if icon:
        link.SetIconLocation(str(icon), 0)
    if aumid:
        store = link.QueryInterface(propsys.IID_IPropertyStore)
        store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(aumid))
        store.Commit()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(lnk), 0)


def create_shortcut(lnk: Path, *, aumid: str | None = None) -> None:
    import pythoncom
    exe, args = launch_command()
    pythoncom.CoInitialize()
    try:
        _write_shortcut(lnk, exe, args, icon_path(), APP_NAME, aumid)
    finally:
        pythoncom.CoUninitialize()
    log.info("Created shortcut %s -> %s", lnk, exe)


def remove_file(path: Path, what: str) -> None:
    try:
        path.unlink()
        log.info("Removed %s: %s", what, path)
    except FileNotFoundError:
        pass
    except OSError:
        log.exception("Could not remove %s: %s", what, path)


def set_startup(enabled: bool) -> None:
    if enabled:
        create_shortcut(startup_shortcut_path())
        log.info("Startup with Windows: ENABLED")
    else:
        remove_file(startup_shortcut_path(), "startup shortcut")
        log.info("Startup with Windows: DISABLED")


# ---------- high level ----------
def is_installed() -> bool:
    try:
        return (is_protocol_current() and _get(_AUMID_KEY, "DisplayName") is not None
                and start_menu_shortcut_path().exists())
    except OSError:
        return False


def install(config: Config) -> list[str]:
    """Idempotent. Creates directories, icon, protocol, AUMID, Start Menu shortcut, startup."""
    lines: list[str] = []
    ensure_app_dir()
    icon_mod.save_ico(icon_path())
    lines.append(f"Data directory:    {app_dir()}")
    register_protocol()
    lines.append(f"Protocol:          {PROTOCOL}://  (HKCU)")
    register_aumid()
    lines.append(f"AppUserModelID:    {AUMID}")
    create_shortcut(start_menu_shortcut_path(), aumid=AUMID)
    lines.append(f"Start Menu link:   {start_menu_shortcut_path()}")
    set_startup(config.startup)
    lines.append("Startup shortcut:  " + (str(startup_shortcut_path()) if config.startup else "not created (disabled in config)"))
    exe, _ = launch_command()
    if not is_frozen():
        lines.append("NOTE: running from source - shortcuts point at the dev interpreter + app.py.")
    lines.append(f"Registered target: {exe}")
    return lines


def uninstall() -> list[str]:
    remove_file(startup_shortcut_path(), "startup shortcut")
    remove_file(start_menu_shortcut_path(), "Start Menu shortcut")
    unregister_protocol()
    unregister_aumid()
    remove_file(icon_path(), "icon")
    return ["Removed startup shortcut, Start Menu shortcut, protocol and AppUserModelID registrations."]
