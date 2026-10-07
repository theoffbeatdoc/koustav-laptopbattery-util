"""Battery / power-state reading via kernel32!GetSystemPowerStatus."""
from __future__ import annotations

import ctypes
import json
import logging
import os
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class PowerState(Enum):
    DISCHARGING = "discharging"          # running on battery
    CHARGING = "charging"                # AC connected and battery actively charging
    AC_NOT_CHARGING = "ac_not_charging"  # AC connected, battery NOT charging (full / OEM charge limit)
    NO_BATTERY = "no_battery"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PowerSample:
    state: PowerState
    percent: int | None
    ac_online: bool | None

    def describe(self) -> str:
        pct = "?" if self.percent is None else f"{self.percent}%"
        labels = {
            PowerState.DISCHARGING: "On battery (discharging)",
            PowerState.CHARGING: "Charging",
            PowerState.AC_NOT_CHARGING: "Plugged in, not charging",
            PowerState.NO_BATTERY: "No battery detected",
            PowerState.UNKNOWN: "Unknown",
        }
        if self.state is PowerState.NO_BATTERY:
            return labels[self.state]
        return f"{pct} - {labels[self.state]}"


# BatteryFlag bits
_FLAG_CHARGING = 8
_FLAG_NO_BATTERY = 128
_UNKNOWN = 255


def classify(ac_line: int, battery_flag: int, percent: int) -> PowerSample:
    """Pure translation of raw SYSTEM_POWER_STATUS values (unit-testable)."""
    ac = True if ac_line == 1 else False if ac_line == 0 else None
    if battery_flag != _UNKNOWN and battery_flag & _FLAG_NO_BATTERY:
        return PowerSample(PowerState.NO_BATTERY, None, ac)
    if battery_flag == _UNKNOWN or percent > 100:
        return PowerSample(PowerState.UNKNOWN, None if percent > 100 else percent, ac)
    if battery_flag & _FLAG_CHARGING:
        return PowerSample(PowerState.CHARGING, percent, True if ac is None else ac)
    if ac is True:
        return PowerSample(PowerState.AC_NOT_CHARGING, percent, ac)
    if ac is False:
        return PowerSample(PowerState.DISCHARGING, percent, ac)
    return PowerSample(PowerState.UNKNOWN, percent, ac)


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


class PowerReader:
    """Reads the current power state.

    Development aid: if env var KBU_FAKE_BATTERY_FILE points at a JSON file such as
    {"percent": 79, "ac": true, "charging": true} that file is read instead of the OS.
    Edit the file while the app runs to simulate plugging/unplugging.
    """

    def __init__(self) -> None:
        self._fake = os.environ.get("KBU_FAKE_BATTERY_FILE") or None
        self._fn = None
        if self._fake:
            log.warning("Using FAKE battery data from %s", self._fake)
        else:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            fn = k32.GetSystemPowerStatus
            fn.argtypes = [ctypes.POINTER(_SystemPowerStatus)]
            fn.restype = wintypes.BOOL
            self._fn = fn

    def read(self) -> PowerSample:
        if self._fake:
            return self._read_fake()
        status = _SystemPowerStatus()
        if not self._fn(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        return classify(status.ACLineStatus, status.BatteryFlag, status.BatteryLifePercent)

    def _read_fake(self) -> PowerSample:
        with open(self._fake, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("no_battery"):
            return classify(1, _FLAG_NO_BATTERY, _UNKNOWN)
        ac = 1 if d.get("ac", False) else 0
        flag = _FLAG_CHARGING if d.get("charging", False) else 0
        return classify(ac, flag, int(d.get("percent", 50)))
