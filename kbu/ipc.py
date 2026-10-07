"""Single-instance mutex + named-pipe channel (second instance -> first instance)."""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from typing import Callable

from .constants import MUTEX_NAME, pipe_name

log = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
_ERR_FILE_NOT_FOUND = 2
_ERR_PIPE_BUSY = 231
_ERR_PIPE_CONNECTED = 535
MAX_MESSAGE = 256


class SingleInstance:
    """Named mutex. ``acquire()`` is False when another instance already owns it."""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._name = name
        self._handle = None
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # use_last_error is essential
        self._k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self._k32.CreateMutexW.restype = wintypes.HANDLE
        self._k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32.CloseHandle.restype = wintypes.BOOL

    def acquire(self) -> bool:
        ctypes.set_last_error(0)
        handle = self._k32.CreateMutexW(None, False, self._name)
        err = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(err)
        if err == ERROR_ALREADY_EXISTS:
            self._k32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle:
            self._k32.CloseHandle(self._handle)
            self._handle = None


def send_message(message: str, wait_seconds: float = 8.0) -> bool:
    """Deliver a short text message to the running instance. Retries while it starts up."""
    import pywintypes
    import win32file

    deadline = time.monotonic() + wait_seconds
    data = message.encode("utf-8")[:MAX_MESSAGE]
    while True:
        try:
            h = win32file.CreateFile(pipe_name(), win32file.GENERIC_WRITE, 0, None,
                                     win32file.OPEN_EXISTING, 0, None)
            try:
                win32file.WriteFile(h, data)
            finally:
                win32file.CloseHandle(h)
            return True
        except pywintypes.error as exc:
            if exc.winerror in (_ERR_FILE_NOT_FOUND, _ERR_PIPE_BUSY) and time.monotonic() < deadline:
                time.sleep(0.1)
                continue
            log.error("Could not reach running instance (%s): %s", exc.winerror, exc.strerror)
            return False


def _owner_only_security():
    """SECURITY_ATTRIBUTES granting the pipe to the current user only (None on failure)."""
    try:
        import ntsecuritycon
        import pywintypes
        import win32api
        import win32security

        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, sid)
        sd = win32security.SECURITY_DESCRIPTOR()
        sd.SetSecurityDescriptorDacl(1, dacl, 0)
        sa = pywintypes.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        return sa
    except Exception:
        log.warning("Could not build owner-only pipe ACL; using default", exc_info=True)
        return None


class IpcServer:
    def __init__(self, handler: Callable[[str], None]) -> None:
        self._handler = handler
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, name="ipc", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            send_message("noop", wait_seconds=0)  # unblock ConnectNamedPipe
        except Exception:
            pass
        if self._thread:
            self._thread.join(2)

    def _serve(self) -> None:
        import pywintypes
        import win32file
        import win32pipe

        sa = _owner_only_security()
        mode = (win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT
                | getattr(win32pipe, "PIPE_REJECT_REMOTE_CLIENTS", 8))
        while not self._stop.is_set():
            pipe = None
            try:
                pipe = win32pipe.CreateNamedPipe(
                    pipe_name(), win32pipe.PIPE_ACCESS_INBOUND, mode,
                    win32pipe.PIPE_UNLIMITED_INSTANCES, 4096, 4096, 0, sa)
                try:
                    win32pipe.ConnectNamedPipe(pipe, None)
                except pywintypes.error as exc:
                    if exc.winerror != _ERR_PIPE_CONNECTED:
                        raise
                if self._stop.is_set():
                    break
                _, data = win32file.ReadFile(pipe, 4096)
                text = bytes(data)[:MAX_MESSAGE].decode("utf-8", "replace").strip()
                if text and text != "noop":
                    log.info("IPC message received: %s", text)
                    try:
                        self._handler(text)
                    except Exception:
                        log.exception("IPC handler failed")
            except Exception:
                log.exception("IPC server error")
                time.sleep(0.5)  # avoid a hot loop if something is persistently broken
            finally:
                if pipe is not None:
                    try:
                        win32pipe.DisconnectNamedPipe(pipe)
                    except Exception:
                        pass
                    try:
                        win32file.CloseHandle(pipe)
                    except Exception:
                        pass
