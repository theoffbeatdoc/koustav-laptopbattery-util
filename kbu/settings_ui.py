"""Settings window (Tkinter / ttk)."""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .config import HIGH_RANGE, INTERVAL_RANGE, LOW_RANGE, Config
from .constants import APP_NAME

log = logging.getLogger(__name__)


class SettingsWindow:
    def __init__(self, root: tk.Tk, config: Config, *, on_save: Callable[[Config], list[str]],
                 read_status: Callable[[], str], integration_ok: bool,
                 on_closed: Callable[[], None], icon_photo=None) -> None:
        self._on_save = on_save
        self._read_status = read_status
        self._on_closed = on_closed
        self.win = win = tk.Toplevel(root)
        win.title(f"{APP_NAME} - Settings")
        win.resizable(False, False)
        if icon_photo is not None:
            win.iconphoto(False, icon_photo)
        style = ttk.Style(win)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Big.TCheckbutton", font=("Segoe UI Semibold", 11))
        style.configure("Err.TLabel", foreground="#b42318")
        style.configure("Ok.TLabel", foreground="#1a7f37")
        style.configure("Warn.TLabel", foreground="#9a6700")

        self.v_enabled = tk.BooleanVar(value=config.enabled)
        self.v_startup = tk.BooleanVar(value=config.startup)
        self.v_low = tk.StringVar(value=str(config.low_threshold))
        self.v_high = tk.StringVar(value=str(config.high_threshold))
        self.v_interval = tk.StringVar(value=str(config.check_interval))

        outer = ttk.Frame(win, padding=16)
        outer.grid(sticky="nsew")
        outer.columnconfigure(0, weight=1)

        ttk.Checkbutton(outer, text="Enable battery monitoring", variable=self.v_enabled,
                        style="Big.TCheckbutton").grid(row=0, column=0, sticky="w")
        self.lbl_status = ttk.Label(outer, text="", foreground="#555")
        self.lbl_status.grid(row=1, column=0, sticky="w", pady=(2, 10))

        box = ttk.LabelFrame(outer, text="Thresholds", padding=12)
        box.grid(row=2, column=0, sticky="ew")
        self._row(box, 0, "Warn when discharging at or below", self.v_low, LOW_RANGE, "%")
        self._row(box, 1, "Warn when charging at or above", self.v_high, HIGH_RANGE, "%")

        box2 = ttk.LabelFrame(outer, text="Polling", padding=12)
        box2.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self._row(box2, 0, "Check battery every", self.v_interval, INTERVAL_RANGE, "seconds")

        ttk.Checkbutton(outer, text="Start automatically with Windows",
                        variable=self.v_startup).grid(row=4, column=0, sticky="w", pady=(12, 0))

        self.lbl_msg = ttk.Label(outer, text="", wraplength=400, justify="left")
        self.lbl_msg.grid(row=5, column=0, sticky="w", pady=(10, 0))
        if not integration_ok:
            ttk.Label(outer, style="Warn.TLabel", wraplength=400, justify="left",
                      text="Windows integration not installed (toast buttons won't work). "
                           "Run the app once with --install.").grid(row=6, column=0, sticky="w", pady=(6, 0))

        btns = ttk.Frame(outer)
        btns.grid(row=7, column=0, sticky="e", pady=(14, 0))
        self.btn_save = ttk.Button(btns, text="Save", command=self._save, default="active")
        self.btn_save.grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="Close", command=self.close).grid(row=0, column=1)

        for v in (self.v_low, self.v_high, self.v_interval):
            v.trace_add("write", lambda *_: self._revalidate())
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Return>", lambda e: self._save())
        win.bind("<Escape>", lambda e: self.close())
        self._closed = False
        self._revalidate()
        self._tick_status()
        self.focus()

    @staticmethod
    def _row(parent, r: int, label: str, var: tk.StringVar, rng: tuple[int, int], unit: str) -> None:
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=3)
        ttk.Spinbox(parent, from_=rng[0], to=rng[1], textvariable=var, width=6).grid(
            row=r, column=1, padx=(12, 6))
        ttk.Label(parent, text=unit).grid(row=r, column=2, sticky="w")
        parent.columnconfigure(0, weight=1)

    # ---- behaviour ----
    def _parse(self) -> tuple[Config | None, str]:
        try:
            low = int(self.v_low.get().strip())
            high = int(self.v_high.get().strip())
            interval = int(self.v_interval.get().strip())
        except ValueError:
            return None, "All numeric fields must be whole numbers."
        cfg = Config(enabled=self.v_enabled.get(), startup=self.v_startup.get(),
                     low_threshold=low, high_threshold=high, check_interval=interval)
        errors = cfg.validate()
        return (None, errors[0]) if errors else (cfg, "")

    def _revalidate(self) -> None:
        cfg, err = self._parse()
        self.btn_save.state(["!disabled"] if cfg else ["disabled"])
        self.lbl_msg.configure(text=err, style="Err.TLabel")

    def _save(self) -> None:
        cfg, err = self._parse()
        if cfg is None:
            return
        try:
            warnings = self._on_save(cfg)
        except Exception as exc:
            log.exception("Saving settings failed")
            messagebox.showerror(APP_NAME, f"Could not save settings:\n{exc}", parent=self.win)
            return
        if warnings:
            messagebox.showwarning(APP_NAME, "\n".join(warnings), parent=self.win)
        self.lbl_msg.configure(text="Saved.", style="Ok.TLabel")

    def _tick_status(self) -> None:
        if self._closed:
            return
        try:
            self.lbl_status.configure(text=f"Battery: {self._read_status()}")
        except Exception:
            self.lbl_status.configure(text="Battery: unavailable")
        self.win.after(2000, self._tick_status)

    def set_enabled(self, enabled: bool) -> None:
        self.v_enabled.set(enabled)

    def focus(self) -> None:
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.attributes("-topmost", True)
            self.win.after(300, lambda: self.win.attributes("-topmost", False))
            self.win.focus_force()
        except tk.TclError:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.win.destroy()
        finally:
            self._on_closed()
