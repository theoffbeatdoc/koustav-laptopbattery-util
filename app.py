"""Koustav Laptop Battery Util - entry point.

Normal run (tray app):      python app.py
Developer helpers:          python app.py --battery-status | --test-notification [upper|final|lower]
                            python app.py --settings
Windows integration:        --install | --uninstall [--purge-data]
Toast button invocation:    app.py "koustav-laptopbattery://action/<name>"  (done by Windows)
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import sys
import traceback

from kbu import __version__
from kbu.constants import APP_NAME, PACKAGE_NAME, Action, parse_action_uri
from kbu.logging_setup import setup_logging

log = logging.getLogger("app")


# ---------------------------------------------------------------- output helpers
_QUIET = False


def emit(text: str, *, error: bool = False) -> None:
    """Print to the console if there is one, otherwise show a message box (windowed EXE).
    With --quiet, informational message boxes are suppressed (errors are always shown)."""
    if sys.stdout is not None:
        print(text, file=sys.stderr if error else sys.stdout)
    elif error or not _QUIET:
        message_box(text, error=error)


def message_box(text: str, *, error: bool = False) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)
    except Exception:
        pass


# ---------------------------------------------------------------- CLI
def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog=PACKAGE_NAME, description=APP_NAME, add_help=True)
    p.add_argument("uri", nargs="?", help="koustav-laptopbattery://action/... (used by toast buttons)")
    p.add_argument("--install", action="store_true", help="register Windows integration and exit")
    p.add_argument("--uninstall", action="store_true", help="remove Windows integration and exit")
    p.add_argument("--purge-data", action="store_true", help="with --uninstall: also delete config and logs")
    p.add_argument("--settings", action="store_true", help="open the Settings window (starts the app if needed)")
    p.add_argument("--quit", action="store_true", help="ask the running instance to exit")
    p.add_argument("--battery-status", "--test-battery", dest="battery_status", action="store_true",
                   help="print battery %%, charging and AC state, then exit")
    p.add_argument("--test-notification", nargs="?", const="upper", choices=["upper", "final", "lower"],
                   help="show a sample toast immediately, then exit")
    p.add_argument("--self-check", action="store_true", help="verify all runtime imports (used by build.ps1)")
    p.add_argument("--quiet", action="store_true", help="no informational message boxes (for scripts)")
    p.add_argument("--debug", action="store_true", help="verbose logging")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p.parse_args(argv)


# ---------------------------------------------------------------- commands
def cmd_battery_status() -> int:
    from kbu.battery import PowerReader
    s = PowerReader().read()
    emit("\n".join([
        f"Battery percentage : {'n/a' if s.percent is None else f'{s.percent}%'}",
        f"Power state        : {s.state.value}",
        f"AC connected       : {'unknown' if s.ac_online is None else s.ac_online}",
        f"Summary            : {s.describe()}",
    ]))
    return 0


def cmd_test_notification(kind: str) -> int:
    from kbu.engine import Kind, ShowToast
    from kbu.notifier import WinRtToastBackend
    effect = {"upper": ShowToast(Kind.UPPER, 80, 80),
              "final": ShowToast(Kind.UPPER, 99, 99, final=True),
              "lower": ShowToast(Kind.LOWER, 20, 20)}[kind]
    WinRtToastBackend().show(effect)
    emit(f"Sent '{kind}' test toast. If nothing appears, check Focus/Do Not Disturb and run --install.")
    return 0


def cmd_install() -> int:
    from kbu import winintegration
    from kbu.config import ConfigStore
    cfg = ConfigStore().load()
    lines = winintegration.install(cfg)
    emit("Installed.\n\n" + "\n".join(lines))
    return 0


def cmd_uninstall(purge: bool) -> int:
    from kbu import winintegration
    from kbu.ipc import send_message
    from kbu.paths import app_dir, config_path
    if send_message("quit", wait_seconds=0):
        note = "Asked the running instance to exit.\n"
    else:
        note = ""
    lines = winintegration.uninstall()
    if purge:
        logging.shutdown()
        for f in list(app_dir().glob("app.log*")) + [config_path(), config_path().with_suffix(".json.corrupt")]:
            try:
                f.unlink()
            except OSError:
                pass
        try:
            app_dir().rmdir()  # only succeeds if empty (the EXE itself may still live there)
        except OSError:
            pass
        lines.append("Deleted config and logs.")
    else:
        lines.append(f"Kept config and logs in {app_dir()} (use --purge-data to delete them).")
    emit(note + "\n".join(lines))
    return 0


def cmd_quit() -> int:
    from kbu.ipc import send_message
    ok = send_message("quit", wait_seconds=0)
    emit("Quit request sent." if ok else "No running instance found.")
    return 0


def cmd_self_check() -> int:
    mods = ["tkinter", "PIL.Image", "PIL.ImageTk", "pystray", "pystray._win32", "pythoncom", "pywintypes",
            "win32api", "win32con", "win32gui", "win32pipe", "win32file", "win32security", "ntsecuritycon",
            "win32com.shell.shell", "win32com.propsys.propsys",
            "winrt.windows.ui.notifications", "winrt.windows.data.xml.dom", "winrt.windows.foundation"]
    import importlib
    failed = []
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as exc:
            failed.append(f"{m}: {exc}")
    try:
        from kbu.engine import Kind, ShowToast
        from kbu.notifier import WinRtToastBackend, build_toast_xml
        WinRtToastBackend()._xml_doc().load_xml(build_toast_xml(ShowToast(Kind.UPPER, 80, 80)))
    except Exception as exc:
        failed.append(f"toast XML: {exc}")
    if failed:
        log.error("Self-check FAILED:\n  %s", "\n  ".join(failed))
        emit("Self-check FAILED:\n" + "\n".join(failed), error=True)
        return 1
    log.info("Self-check passed")
    if sys.stdout is not None:
        print("Self-check passed.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Normal start / second-instance forwarding."""
    from kbu.ipc import SingleInstance, send_message

    action: Action | None = None
    if args.uri:
        action = parse_action_uri(args.uri)
        if action is None:
            log.warning("Ignoring unrecognised URI: %r", args.uri)
            return 0

    instance = SingleInstance()
    if not instance.acquire():
        message = f"action:{action.value}" if action else "settings"
        log.info("Another instance is running; forwarding %r", message)
        if send_message(message):
            return 0
        log.error("Single-instance: running instance did not respond")
        if not action:
            message_box("Another copy is running but did not respond.\nSee app.log for details.", error=True)
        return 1

    if action is not None:
        # Stale toast button pressed while the app isn't running: don't start up for it.
        log.info("No running instance to receive %s; ignoring", action.value)
        instance.release()
        return 0

    from kbu.application import Application
    return Application(instance, open_settings=args.settings).run()


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    global _QUIET
    args = parse_args(argv)
    _QUIET = args.quiet
    setup_logging(debug=args.debug)
    try:
        if args.self_check:
            return cmd_self_check()
        if args.battery_status:
            return cmd_battery_status()
        if args.test_notification:
            return cmd_test_notification(args.test_notification)
        if args.install:
            return cmd_install()
        if args.uninstall:
            return cmd_uninstall(args.purge_data)
        if args.quit:
            return cmd_quit()
        return cmd_run(args)
    except Exception as exc:
        log.critical("Fatal error", exc_info=True)
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        emit(f"{APP_NAME} failed:\n{detail}\n\nSee %LOCALAPPDATA%\\KoustavLaptopBatteryUtil\\app.log", error=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
