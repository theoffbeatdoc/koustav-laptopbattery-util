"""Configuration model, validation and persistence."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from typing import Any

from .paths import config_path, ensure_app_dir

log = logging.getLogger(__name__)

LOW_RANGE = (1, 98)
HIGH_RANGE = (2, 99)
INTERVAL_RANGE = (5, 300)


@dataclass(frozen=True)
class Config:
    enabled: bool = True
    startup: bool = True
    low_threshold: int = 20
    high_threshold: int = 80
    check_interval: int = 30

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not LOW_RANGE[0] <= self.low_threshold <= LOW_RANGE[1]:
            errors.append(f"Low threshold must be between {LOW_RANGE[0]} and {LOW_RANGE[1]}%.")
        if not HIGH_RANGE[0] <= self.high_threshold <= HIGH_RANGE[1]:
            errors.append(f"High threshold must be between {HIGH_RANGE[0]} and {HIGH_RANGE[1]}%.")
        if not errors and self.low_threshold >= self.high_threshold:
            errors.append("Low threshold must be lower than the high threshold.")
        if not INTERVAL_RANGE[0] <= self.check_interval <= INTERVAL_RANGE[1]:
            errors.append(f"Polling interval must be {INTERVAL_RANGE[0]}-{INTERVAL_RANGE[1]} seconds.")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def parse_config(raw: dict[str, Any]) -> tuple[Config, bool]:
    """Build a valid Config from untrusted JSON. Returns (config, was_modified)."""
    d = Config()
    changed = False

    def pick(name: str, kind: str, lo: int = 0, hi: int = 0):
        nonlocal changed
        default = getattr(d, name)
        v = raw.get(name, default)
        ok = isinstance(v, bool) if kind == "bool" else (_is_int(v) and lo <= v <= hi)
        if not ok:
            log.warning("Config: invalid %s=%r, using default %r", name, v, default)
            changed = True
            return default
        if name not in raw:
            changed = True
        return v

    cfg = Config(
        enabled=pick("enabled", "bool"),
        startup=pick("startup", "bool"),
        low_threshold=pick("low_threshold", "int", *LOW_RANGE),
        high_threshold=pick("high_threshold", "int", *HIGH_RANGE),
        check_interval=pick("check_interval", "int", *INTERVAL_RANGE),
    )
    if cfg.low_threshold >= cfg.high_threshold:
        log.warning("Config: low (%s) >= high (%s); resetting thresholds",
                    cfg.low_threshold, cfg.high_threshold)
        cfg = Config(cfg.enabled, cfg.startup, d.low_threshold, d.high_threshold, cfg.check_interval)
        changed = True
    return cfg, changed


class ConfigStore:
    def __init__(self) -> None:
        self.path = config_path()

    def load(self) -> Config:
        if not self.path.exists():
            log.info("No config found, creating defaults at %s", self.path)
            cfg = Config()
            self.save(cfg)
            return cfg
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("top-level JSON value is not an object")
        except (OSError, ValueError) as exc:
            log.error("Config unreadable (%s); falling back to defaults", exc)
            try:
                self.path.replace(self.path.with_suffix(".json.corrupt"))
            except OSError:
                pass
            cfg = Config()
            self.save(cfg)
            return cfg
        cfg, changed = parse_config(raw)
        if changed:
            log.info("Config repaired; rewriting")
            self.save(cfg)
        return cfg

    def save(self, cfg: Config) -> None:
        errors = cfg.validate()
        if errors:
            raise ValueError("; ".join(errors))
        ensure_app_dir()
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix="config.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cfg.to_dict(), f, indent=2)
                f.write("\n")
            os.replace(tmp, self.path)  # atomic
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
