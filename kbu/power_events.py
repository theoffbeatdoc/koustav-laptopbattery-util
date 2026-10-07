"""Sleep/resume and AC-change notifications via a hidden top-level window.

(Message-only windows do NOT receive broadcast messages, so a normal hidden window
is used.) Polling alone would also recover; this just makes it faster and more precise.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMPOWERSTATUSCHANGE = 0x000A
PBT_APMRESUMEAUTOMATIC = 0x0012


class PowerEventListener:
    def __init__(self, callback: Callable[[str], None]) -> None:
        self._callback = callback
        self._hwnd = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="power-events", daemon=True)
        self._thread.start()
        self._ready.wait(3)

    def stop(self) -> None:
        if self._hwnd:
            try:
                import win32con
                import win32gui
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                log.debug("Power window close failed", exc_info=True)
        if self._thread:
            self._thread.join(2)

    def _on_power(self, hwnd, msg, wparam, lparam):
        kind = {
            PBT_APMSUSPEND: "suspend",
            PBT_APMRESUMESUSPEND: "resume",
            PBT_APMRESUMEAUTOMATIC: "resume",
            PBT_APMPOWERSTATUSCHANGE: "power-status",
        }.get(wparam)
        if kind:
            try:
                self._callback(kind)
            except Exception:
                log.exception("Power event callback failed")
        return True

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        import win32gui
        win32gui.PostQuitMessage(0)
        return 0

    def _run(self) -> None:
        try:
            import win32api
            import win32con
            import win32gui

            wc = win32gui.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName = "KoustavLaptopBatteryUtil.PowerWindow"
            wc.lpfnWndProc = {WM_POWERBROADCAST: self._on_power, win32con.WM_DESTROY: self._on_destroy}
            atom = win32gui.RegisterClass(wc)
            self._hwnd = win32gui.CreateWindow(atom, "KBU power events", 0, 0, 0, 0, 0, 0, 0,
                                               wc.hInstance, None)
            self._ready.set()
            win32gui.PumpMessages()
        except Exception:
            log.exception("Power event listener failed (polling will still recover after resume)")
        finally:
            self._ready.set()
