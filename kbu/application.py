"""The tray application: wires config, engine, monitor, notifier, tray, IPC and UI."""
from __future__ import annotations

import ctypes
import dataclasses
import logging
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from . import __version__, winintegration
from .battery import PowerReader, PowerSample
from .config import Config, ConfigStore
from .constants import APP_NAME, Action
from .engine import AlertEngine, ClearToast, Effect, Kind
from .icon import make_icon_image
from .ipc import IpcServer, SingleInstance
from .logging_setup import upgrade_to_rotating
from .monitor import Monitor
from .notifier import Notifier
from .paths import is_frozen
from .power_events import PowerEventListener
from .settings_ui import SettingsWindow
from .tray import TrayIcon

log = logging.getLogger(__name__)


class Application:
    def __init__(self, instance: SingleInstance, *, open_settings: bool = False) -> None:
        self._instance = instance
        self._open_settings_on_start = open_settings
        self._ui: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._closing = False
        self._cfg_lock = threading.Lock()
        self._settings: SettingsWindow | None = None
        self._icon_photo = None
        self.root: tk.Tk | None = None
        self.config = Config()
        self.engine: AlertEngine | None = None
        self.reader: PowerReader | None = None
        self.notifier: Notifier | None = None
        self.monitor: Monitor | None = None
        self.tray: TrayIcon | None = None
        self.ipc: IpcServer | None = None
        self.power: PowerEventListener | None = None

    # ------------------------------------------------------------ lifecycle
    def run(self) -> int:
        upgrade_to_rotating()
        log.info("=== %s %s starting (frozen=%s) ===", APP_NAME, __version__, is_frozen())
        try:
            self._start()
            assert self.root is not None
            self.root.mainloop()
            return 0
        finally:
            self._shutdown()

    def _start(self) -> None:
        self._store = ConfigStore()
        self.config = self._store.load()
        log.info("Config: %s", self.config)

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.report_callback_exception = lambda *a: log.error("Tk callback error", exc_info=a)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family="Segoe UI", size=10)
            except tk.TclError:
                pass
        try:
            from PIL import ImageTk
            self._icon_photo = ImageTk.PhotoImage(make_icon_image(64))
        except Exception:
            log.debug("Could not create window icon", exc_info=True)

        self.reader = PowerReader()
        self.engine = AlertEngine(self.config)
        self.notifier = Notifier()
        self.notifier.start()
        self.monitor = Monitor(self.engine, self.reader, lambda: self.config,
                               self._dispatch_effects, self._on_sample)
        self.ipc = IpcServer(self._on_message)
        self.ipc.start()
        self.power = PowerEventListener(self._on_power_event)
        self.power.start()
        self.tray = TrayIcon(on_settings=lambda: self.post(self._show_settings),
                             on_toggle=self.toggle_enabled,
                             is_enabled=lambda: self.config.enabled,
                             on_exit=self.request_exit)
        self.tray.start()
        self.monitor.start()
        if not winintegration.is_installed():
            log.warning("Windows integration is not installed/current; toast buttons will not work "
                        "until you run the app with --install")
        self.root.after(150, self._pump)
        if self._open_settings_on_start:
            self.post(self._show_settings)
        log.info("Startup complete")

    def _shutdown(self) -> None:
        self._closing = True
        log.info("Shutting down")

        def step(name: str, fn: Callable[[], None]) -> None:
            try:
                fn()
            except Exception:
                log.exception("Shutdown step failed: %s", name)

        if self.monitor:
            step("monitor", self.monitor.stop)
        if self.notifier:
            for kind in (Kind.UPPER, Kind.LOWER):  # don't leave toasts whose buttons would be dead
                self.notifier.submit(ClearToast(kind))
            step("notifier", self.notifier.stop)
        if self.power:
            step("power", self.power.stop)
        if self.ipc:
            step("ipc", self.ipc.stop)
        if self.tray:
            step("tray", self.tray.stop)
        if self.root:
            step("tk", self.root.destroy)
        step("mutex", self._instance.release)
        log.info("=== shutdown complete ===")

    # ------------------------------------------------------------ UI thread bridge
    def post(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` on the Tk thread (safe to call from any thread)."""
        self._ui.put(fn)

    def _pump(self) -> None:
        try:
            while True:
                fn = self._ui.get_nowait()
                try:
                    fn()
                except Exception:
                    log.exception("UI task failed")
        except queue.Empty:
            pass
        if not self._closing and self.root:
            self.root.after(150, self._pump)

    def request_exit(self) -> None:
        log.info("Exit requested")
        self.post(lambda: self.root.quit())

    # ------------------------------------------------------------ settings window
    def _show_settings(self) -> None:
        if self._settings is not None:
            self._settings.focus()
            return
        self._settings = SettingsWindow(
            self.root, self.config, on_save=self.update_config,
            read_status=lambda: self.reader.read().describe(),
            integration_ok=winintegration.is_installed(),
            on_closed=lambda: setattr(self, "_settings", None),
            icon_photo=self._icon_photo)

    # ------------------------------------------------------------ config changes
    def update_config(self, new: Config) -> list[str]:
        """Persist + apply a new configuration. Returns user-visible warnings."""
        warnings: list[str] = []
        with self._cfg_lock:
            old, self.config = self.config, new
        self._store.save(new)
        changes = {k: (v, getattr(new, k)) for k, v in dataclasses.asdict(old).items()
                   if v != getattr(new, k)}
        log.info("Configuration changed: %s", changes or "no changes")
        self._dispatch_effects(self.engine.update_config(new))
        if old.startup != new.startup:
            try:
                winintegration.set_startup(new.startup)
            except Exception as exc:
                log.exception("Updating startup shortcut failed")
                warnings.append(f"Settings were saved, but the startup shortcut could not be updated:\n{exc}")
        self.monitor.wake()
        if self.tray:
            self.tray.refresh()
        if not new.enabled and self.tray:
            self.tray.set_tooltip(f"{APP_NAME} - monitoring disabled")
        return warnings

    def toggle_enabled(self) -> None:
        new = dataclasses.replace(self.config, enabled=not self.config.enabled)
        log.info("User toggled monitoring from tray -> %s", "enabled" if new.enabled else "disabled")
        self.update_config(new)
        self.post(lambda: self._settings and self._settings.set_enabled(new.enabled))

    # ------------------------------------------------------------ effects, samples, events
    def _dispatch_effects(self, effects: list[Effect]) -> None:
        for e in effects:
            self.notifier.submit(e)

    def _on_sample(self, sample: PowerSample | None) -> None:
        if self.tray is None:
            return
        if sample is None:
            self.tray.set_tooltip(f"{APP_NAME} - monitoring disabled")
        else:
            self.tray.set_tooltip(f"{APP_NAME}\n{sample.describe()}")

    def _on_message(self, msg: str) -> None:
        """Messages from other instances (runs on the IPC thread)."""
        if msg == "settings":
            self.post(self._show_settings)
        elif msg == "quit":
            self.request_exit()
        elif msg.startswith("action:"):
            try:
                action = Action(msg.split(":", 1)[1])
            except ValueError:
                log.warning("Rejected unknown action: %r", msg)
                return
            log.info("User action: %s", action.value)
            self.engine.handle_action(action)
            self.monitor.wake()  # re-evaluate immediately (e.g. already at 99% after "Allow 99%")
        else:
            log.warning("Ignored unknown IPC message: %r", msg)

    def _on_power_event(self, kind: str) -> None:
        log.info("Power event: %s", kind)
        if kind == "suspend":
            return
        # Re-read now and again shortly after: right after resume the battery driver can
        # still report stale values. No state is reset here, so no duplicate notification.
        self.monitor.wake()
        t = threading.Timer(4.0, self.monitor.wake)
        t.daemon = True
        t.start()
