"""Display and idle-state control.

The nearest useful thing to "unlock the PC", which Windows does not permit:
once the session is locked, the logon UI runs on a separate secure desktop that
no ordinary process can reach, and there is deliberately no counterpart to
LockWorkStation. What can be done is keep the machine from going dark in the
first place, and wake the display when it has.

Both work only while the session is unlocked.
"""
from __future__ import annotations

import ctypes
import logging
import subprocess
import threading
import time

import psutil

from . import foreground, hotkeys

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

log = logging.getLogger("phonedeck.power")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# SetThreadExecutionState flags.
ES_CONTINUOUS = 0x80000000        # the state persists rather than being a nudge
ES_SYSTEM_REQUIRED = 0x00000001   # do not sleep
ES_DISPLAY_REQUIRED = 0x00000002  # do not switch the display off


class _KeepAwake:
    """Holds the machine awake for as long as it is switched on.

    SetThreadExecutionState applies to the *calling thread* and lasts only as
    long as that thread does, so a request handler cannot set it -- the thread
    ends with the response and the state dies with it. A dedicated thread owns
    the state instead, and simply stays alive.
    """

    def __init__(self) -> None:
        self._enabled = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="keep-awake",
                                        daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        applied = False
        while True:
            with self._lock:
                wanted = self._enabled
            if wanted != applied:
                flags = ES_CONTINUOUS
                if wanted:
                    flags |= ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
                if kernel32.SetThreadExecutionState(flags) == 0:
                    log.warning("SetThreadExecutionState failed")
                else:
                    applied = wanted
                    log.info("keep awake: %s", "on" if wanted else "off")
            time.sleep(0.4)

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set(self, value: bool) -> bool:
        with self._lock:
            self._enabled = value
        self.start()
        return value

    def toggle(self) -> bool:
        with self._lock:
            self._enabled = not self._enabled
            value = self._enabled
        self.start()
        return value


keep_awake = _KeepAwake()


# ------------------------------------------------------- session control ----
WM_CLOSE = 0x0010

user32 = ctypes.WinDLL("user32", use_last_error=True)

# Closing these would break the desktop or kill PhoneDeck itself, so they are
# never asked to close even when everything else is.
PROTECTED = {
    "explorer", "dwm", "sihost", "ctfmon", "textinputhost",
    "applicationframehost", "shellexperiencehost", "searchhost",
    "startmenuexperiencehost", "lockapp", "python", "pythonw",
}

_MODES = {
    "shutdown": ["/s"],
    "restart": ["/r"],
    "logoff": ["/l"],
    "abort": ["/a"],
}


def system_power(mode: str, delay: int = 0) -> str:
    """Shut down, restart, sign out, or cancel a pending one.

    Deliberately without ``/f``: applications get the chance to prompt about
    unsaved work rather than being killed. A non-zero ``delay`` gives Windows'
    own cancel window, and ``abort`` calls it off.
    """
    mode = mode.lower()
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {', '.join(_MODES)}, not {mode!r}")

    argv = ["shutdown.exe", *_MODES[mode]]
    # /l and /a take no timeout.
    if mode in ("shutdown", "restart"):
        argv += ["/t", str(max(0, int(delay)))]

    proc = subprocess.run(argv, capture_output=True, text=True,
                          creationflags=NO_WINDOW)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        # 1116: nothing was scheduled, which is not worth calling a failure.
        if mode == "abort" and "1116" in message:
            return "no shutdown was pending"
        raise OSError(message or f"shutdown exited {proc.returncode}")

    if mode == "abort":
        return "shutdown cancelled"
    if delay:
        return f"{mode} in {delay}s (tap Cancel Shutdown to stop it)"
    return f"{mode} now"


def close_all_windows(keep: list[str] | None = None,
                      only: list[str] | None = None) -> str:
    """Politely ask open application windows to close.

    Sends WM_CLOSE, the same message the X button sends, so anything with
    unsaved work prompts rather than losing it. Nothing is force-killed.
    """
    def clean(names):
        return {str(n).lower().removesuffix(".exe") for n in (names or [])}

    keep_set = PROTECTED | clean(keep)
    only_set = clean(only) or None

    closed: list[str] = []
    for hwnd, pid in foreground.visible_windows().items():
        try:
            name = psutil.Process(pid).name().lower().removesuffix(".exe")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if only_set is not None:
            if name not in only_set:
                continue
        elif name in keep_set:
            continue

        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        closed.append(name)

    if not closed:
        return "nothing to close"
    log.info("asked to close: %s", ", ".join(sorted(set(closed))))
    return f"closing {len(closed)} window(s)"


def wake_display() -> str:
    """Switch a sleeping display back on.

    A zero-distance mouse move registers as user activity, which is enough to
    wake the panel without moving the pointer or pressing anything. Does
    nothing useful if the session is locked -- input cannot reach the secure
    desktop.
    """
    hotkeys.move_mouse_relative(0, 0)
    return "display woken"
