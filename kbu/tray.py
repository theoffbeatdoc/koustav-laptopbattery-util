"""System tray icon (pystray) running on its own thread."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .constants import APP_NAME
from .icon import make_icon_image

log = logging.getLogger(__name__)


class TrayIcon:
    def __init__(self, *, on_settings: Callable[[], None], on_toggle: Callable[[], None],
                 is_enabled: Callable[[], bool], on_exit: Callable[[], None]) -> None:
        self._on_settings = on_settings
        self._on_toggle = on_toggle
        self._is_enabled = is_enabled
        self._on_exit = on_exit
        self._icon = None
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._tooltip = APP_NAME

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()

    def _build(self):
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("Settings...", lambda icon, item: self._safe(self._on_settings), default=True),
            pystray.MenuItem("Monitoring enabled", lambda icon, item: self._safe(self._on_toggle),
                             checked=lambda item: self._is_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda icon, item: self._safe(self._on_exit)),
        )
        return pystray.Icon("KoustavLaptopBatteryUtil", make_icon_image(64, self._is_enabled()),
                            self._tooltip, menu)

    def _run(self) -> None:
        failures = 0
        while not self._stopping and failures < 3:
            try:
                self._icon = self._build()
                self._icon.run()  # blocks until stop()
                return
            except Exception:
                failures += 1
                log.exception("Tray icon failed (attempt %d/3)", failures)
                time.sleep(2)
        if not self._stopping:
            log.error("Tray icon unavailable; monitoring continues without it")

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            log.exception("Tray menu action failed")

    def refresh(self) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.icon = make_icon_image(64, self._is_enabled())
            icon.update_menu()
        except Exception:
            log.debug("Tray refresh failed", exc_info=True)

    def set_tooltip(self, text: str) -> None:
        text = text[:120]
        if text == self._tooltip:
            return
        self._tooltip = text
        icon = self._icon
        if icon is not None:
            try:
                icon.title = text
            except Exception:
                log.debug("Tray tooltip update failed", exc_info=True)

    def stop(self) -> None:
        self._stopping = True
        icon = self._icon
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                log.debug("Tray stop failed", exc_info=True)
        if self._thread:
            self._thread.join(2)
