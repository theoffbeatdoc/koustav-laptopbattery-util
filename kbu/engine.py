"""Notification state machine.

Pure logic: no Windows, no threads of its own, injectable clock. The monitor feeds it
power samples (``tick``), toast button presses arrive via ``handle_action``; it returns
*effects* (show / clear a toast) for the caller to execute.

Cycle model
-----------
* AC cycle      - starts when AC is connected (CHARGING or AC_NOT_CHARGING).
                  Owns: upper alert state + the temporary 99% override.
* Battery cycle - starts when AC is disconnected (DISCHARGING).
                  Owns: lower alert state.
Switching between the two (or starting up) begins a new cycle and resets everything,
so "plug in again at 85%" is a fresh charging cycle.

Each alert is: shown (fired once for the current target) / ignored (until cycle end) /
renotify_at (at most ONE pending deadline; re-evaluated when it expires).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .battery import PowerSample, PowerState
from .config import Config
from .constants import OVERRIDE_TARGET, RENOTIFY_SECONDS, Action

log = logging.getLogger(__name__)


class Kind(str, Enum):
    UPPER = "upper"
    LOWER = "lower"


@dataclass(frozen=True)
class ShowToast:
    kind: Kind
    percent: int
    target: int          # the threshold this alert is for (80, or 99 with override)
    final: bool = False  # True when target is already the 99% ceiling


@dataclass(frozen=True)
class ClearToast:
    kind: Kind


Effect = ShowToast | ClearToast


class _Mode(Enum):
    AC = "ac"
    BATTERY = "battery"


@dataclass
class _Alert:
    shown: bool = False
    ignored: bool = False
    renotify_at: float | None = None

    def reset(self) -> None:
        self.shown = False
        self.ignored = False
        self.renotify_at = None


class AlertEngine:
    def __init__(self, config: Config, clock: Callable[[], float] = time.time) -> None:
        self._cfg = config
        self._clock = clock  # wall clock on purpose: monotonic clocks may pause in sleep
        self._lock = threading.RLock()
        self._mode: _Mode | None = None
        self._upper = _Alert()
        self._lower = _Alert()
        self._override99 = False

    # ---- introspection -------------------------------------------------
    @property
    def effective_upper_target(self) -> int:
        with self._lock:
            return self._target()

    def next_deadline(self) -> float | None:
        with self._lock:
            ds = [a.renotify_at for a in (self._upper, self._lower) if a.renotify_at is not None]
            return min(ds) if ds else None

    def _target(self) -> int:
        return max(self._cfg.high_threshold, OVERRIDE_TARGET) if self._override99 else self._cfg.high_threshold

    # ---- configuration -------------------------------------------------
    def update_config(self, new: Config) -> list[Effect]:
        with self._lock:
            old, self._cfg = self._cfg, new
            effects: list[Effect] = []
            if not new.enabled:
                if old.enabled:
                    effects += self._clear_alerts()
                    self._override99 = False
                    self._mode = None
                    log.info("Monitoring disabled: alert state cleared")
                return effects
            if not old.enabled:
                self._mode = None  # next tick starts a fresh cycle and re-evaluates
                log.info("Monitoring enabled: starting fresh")
                return effects
            if new.high_threshold != old.high_threshold:
                if self._upper.shown:
                    effects.append(ClearToast(Kind.UPPER))
                self._upper.reset()
            if new.low_threshold != old.low_threshold:
                if self._lower.shown:
                    effects.append(ClearToast(Kind.LOWER))
                self._lower.reset()
            return effects

    # ---- polling -------------------------------------------------------
    def tick(self, sample: PowerSample) -> list[Effect]:
        with self._lock:
            if not self._cfg.enabled:
                return []
            if sample.state in (PowerState.UNKNOWN, PowerState.NO_BATTERY) or sample.percent is None:
                return []
            mode = _Mode.AC if sample.state in (PowerState.CHARGING, PowerState.AC_NOT_CHARGING) \
                else _Mode.BATTERY
            effects: list[Effect] = []
            if mode is not self._mode:
                effects += self._begin_cycle(mode)
            now = self._clock()
            pct = sample.percent
            if mode is _Mode.AC:
                target = self._target()
                effects += self._evaluate(
                    self._upper, now,
                    triggers=sample.state is PowerState.CHARGING and pct >= target,
                    applies=pct >= target,
                    make=lambda: ShowToast(Kind.UPPER, pct, target, final=target >= OVERRIDE_TARGET),
                )
            else:
                low = self._cfg.low_threshold
                effects += self._evaluate(
                    self._lower, now,
                    triggers=pct <= low,
                    applies=pct <= low,
                    make=lambda: ShowToast(Kind.LOWER, pct, low),
                )
            return effects

    def _begin_cycle(self, mode: _Mode) -> list[Effect]:
        effects = self._clear_alerts()
        self._override99 = False
        self._mode = mode
        log.info("New %s cycle started (alert state reset)",
                 "charging/AC" if mode is _Mode.AC else "discharging")
        return effects

    def _clear_alerts(self) -> list[Effect]:
        effects: list[Effect] = []
        for kind, alert in ((Kind.UPPER, self._upper), (Kind.LOWER, self._lower)):
            if alert.shown:
                effects.append(ClearToast(kind))
            alert.reset()
        return effects

    def _evaluate(self, alert: _Alert, now: float, *, triggers: bool, applies: bool,
                  make: Callable[[], ShowToast]) -> list[Effect]:
        # 1) A pending "renotify" whose time has come. Always consumed; only shown if the
        #    condition still applies *right now* (re-evaluated, never blindly fired).
        if alert.renotify_at is not None and now >= alert.renotify_at:
            alert.renotify_at = None
            if applies and not alert.ignored:
                alert.shown = True
                log.info("Renotify timer expired, condition still applies: notifying again")
                return [make()]
            log.info("Renotify timer expired but condition no longer applies: dropped")
        # 2) Normal one-shot trigger (level-based, so starting above the threshold works).
        if alert.ignored or alert.shown:
            return []
        if triggers:
            alert.shown = True
            return [make()]
        return []

    # ---- toast button presses -----------------------------------------
    def handle_action(self, action: Action) -> bool:
        """Apply a toast action. Returns False if it was stale/invalid and ignored."""
        with self._lock:
            if not self._cfg.enabled:
                log.info("Action %s ignored: monitoring disabled", action.value)
                return False
            now = self._clock()
            upper, lower = self._upper, self._lower
            ok = False
            if action is Action.RENOTIFY_UPPER:
                if self._mode is _Mode.AC and upper.shown and not upper.ignored:
                    upper.renotify_at = now + RENOTIFY_SECONDS  # replaces any pending one
                    ok = True
            elif action is Action.IGNORE_UPPER:
                if self._mode is _Mode.AC and upper.shown:
                    upper.ignored = True
                    upper.renotify_at = None
                    ok = True
            elif action is Action.CHARGE_99:
                if (self._mode is _Mode.AC and upper.shown and not self._override99
                        and self._cfg.high_threshold < OVERRIDE_TARGET):
                    self._override99 = True  # temporary; config untouched
                    upper.reset()            # new target -> eligible to fire again at 99
                    ok = True
            elif action is Action.RENOTIFY_LOWER:
                if self._mode is _Mode.BATTERY and lower.shown and not lower.ignored:
                    lower.renotify_at = now + RENOTIFY_SECONDS
                    ok = True
            elif action is Action.IGNORE_LOWER:
                if self._mode is _Mode.BATTERY and lower.shown:
                    lower.ignored = True
                    lower.renotify_at = None
                    ok = True
            log.info("Action %s %s", action.value, "applied" if ok else "ignored (stale or not applicable)")
            return ok
