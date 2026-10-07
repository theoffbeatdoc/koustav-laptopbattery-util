"""Native Windows toast notifications via the WinRT projection (pywinrt).

All WinRT calls happen on one dedicated worker thread so they never touch the Tk/tray
threads (avoids COM apartment conflicts) and a slow/failed toast never blocks monitoring.
"""
from __future__ import annotations

import logging
import queue
import threading
from xml.sax.saxutils import escape, quoteattr

from .constants import AUMID, OVERRIDE_TARGET, TOAST_GROUP, Action, action_uri
from .engine import ClearToast, Effect, Kind, ShowToast

log = logging.getLogger(__name__)


def _content(effect: ShowToast) -> tuple[str, str, list[tuple[str, Action]]]:
    if effect.kind is Kind.UPPER:
        if effect.final:
            return (f"Battery is at {effect.percent}%",
                    f"Battery has reached {effect.percent}%. Unplug the charger when convenient.",
                    [("Renotify in 5 mins", Action.RENOTIFY_UPPER), ("Ignore", Action.IGNORE_UPPER)])
        return ("Battery charge limit reached",
                f"Battery is at {effect.percent}%. Your configured limit is {effect.target}%.",
                [("Renotify in 5 mins", Action.RENOTIFY_UPPER),
                 (f"Allow charge to {OVERRIDE_TARGET}%", Action.CHARGE_99),
                 ("Ignore", Action.IGNORE_UPPER)])
    return ("Battery is getting low",
            f"Battery is at {effect.percent}%. Consider connecting the charger.",
            [("Renotify in 5 mins", Action.RENOTIFY_LOWER), ("Ignore", Action.IGNORE_LOWER)])


def build_toast_xml(effect: ShowToast) -> str:
    title, body, buttons = _content(effect)
    actions = "".join(
        f'<action content={quoteattr(label)} arguments={quoteattr(action_uri(act))} '
        f'activationType="protocol"/>' for label, act in buttons)
    # scenario="reminder": pre-expanded and stays on screen until dismissed/acted on
    # (Windows policy such as Focus/Do Not Disturb can still suppress or defer it).
    return (
        '<toast scenario="reminder">'
        '<visual><binding template="ToastGeneric">'
        f"<text>{escape(title)}</text><text>{escape(body)}</text>"
        "</binding></visual>"
        f"<actions>{actions}</actions>"
        '<audio src="ms-winsoundevent:Notification.Reminder"/>'
        "</toast>"
    )


class WinRtToastBackend:
    def __init__(self) -> None:
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import ToastNotification, ToastNotificationManager
        self._xml_doc = XmlDocument
        self._toast = ToastNotification
        self._mgr = ToastNotificationManager

    def show(self, effect: ShowToast) -> None:
        doc = self._xml_doc()
        doc.load_xml(build_toast_xml(effect))
        toast = self._toast(doc)
        toast.tag = effect.kind.value      # same tag+group replaces the old toast: no stacking
        toast.group = TOAST_GROUP
        notifier = self._mgr.create_toast_notifier_with_id(AUMID)
        notifier.show(toast)
        try:
            setting = notifier.setting
            name = getattr(setting, "name", str(setting))
            if name != "ENABLED":
                log.warning("Windows reports notifications are not fully enabled for this app: %s", name)
        except Exception:  # purely diagnostic
            pass

    def clear(self, kind: Kind) -> None:
        self._mgr.history.remove_grouped_tag_with_id(kind.value, TOAST_GROUP, AUMID)


class Notifier:
    def __init__(self) -> None:
        self._q: queue.Queue[Effect | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="notifier", daemon=True)
        self._thread.start()

    def submit(self, effect: Effect) -> None:
        self._q.put(effect)

    def stop(self, timeout: float = 3.0) -> None:
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        backend: WinRtToastBackend | None = None
        while True:
            item = self._q.get()
            if item is None:
                return
            try:
                if backend is None:
                    backend = WinRtToastBackend()
                if isinstance(item, ShowToast):
                    log.info("Showing %s toast (battery %s%%, target %s%%, final=%s)",
                             item.kind.value, item.percent, item.target, item.final)
                    backend.show(item)
                else:
                    log.info("Clearing %s toast", item.kind.value)
                    try:
                        backend.clear(item.kind)
                    except Exception as exc:  # nothing to clear is not an error worth escalating
                        log.debug("Clear failed: %s", exc)
            except Exception:
                log.exception("Notification failed (monitoring continues)")
                backend = None  # re-create on next attempt
