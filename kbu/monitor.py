"""Background polling thread. Sleeps on an Event (no busy loop); can be woken early."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .battery import PowerReader, PowerSample, PowerState
from .config import Config
from .engine import AlertEngine, Effect

log = logging.getLogger(__name__)


class Monitor:
    def __init__(self, engine: AlertEngine, reader: PowerReader, get_config: Callable[[], Config],
                 on_effects: Callable[[list[Effect]], None],
                 on_sample: Callable[[PowerSample | None], None]) -> None:
        self._engine = engine
        self._reader = reader
        self._get_config = get_config
        self._on_effects = on_effects
        self._on_sample = on_sample
        self._wake_evt = threading.Event()
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_logged: tuple | None = None
        self._last_error: str | None = None
        self._error_count = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        self._wake_evt.set()
        if self._thread:
            self._thread.join(3)

    def wake(self) -> None:
        """Request an immediate re-poll (config change, action, resume, AC change...)."""
        self._wake_evt.set()

    def _run(self) -> None:
        log.info("Monitor thread started")
        while not self._stop_evt.is_set():
            try:
                self._poll_once()
            except Exception:
                log.exception("Unexpected error in monitor loop (will retry)")
            self._wake_evt.wait(self._timeout())
            self._wake_evt.clear()
        log.info("Monitor thread stopped")

    def _timeout(self) -> float | None:
        cfg = self._get_config()
        if not cfg.enabled:
            return None  # fully idle until woken
        timeout = float(cfg.check_interval)
        deadline = self._engine.next_deadline()
        if deadline is not None:
            timeout = min(timeout, max(1.0, deadline - time.time()))
        return timeout

    def _poll_once(self) -> None:
        cfg = self._get_config()
        if not cfg.enabled:
            self._on_sample(None)
            return
        try:
            sample = self._reader.read()
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            self._error_count += 1
            if msg != self._last_error or self._error_count % 20 == 0:
                log.error("Battery poll failed (%s); retrying next cycle", msg)
                self._last_error = msg
            return
        self._last_error, self._error_count = None, 0
        key = (sample.state, sample.percent)
        if key != self._last_logged:
            log.info("Battery state: %s", sample.describe())
            if sample.state is PowerState.NO_BATTERY:
                log.info("No battery present - idling")
            self._last_logged = key
        self._on_sample(sample)
        effects = self._engine.tick(sample)
        if effects:
            try:
                self._on_effects(effects)
            except Exception:
                log.exception("Failed to dispatch notification effects")
