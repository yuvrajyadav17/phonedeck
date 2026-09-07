"""The ADB bridge -- how the PC reaches out and drives the phone.

This is the piece that makes "the app opens by itself when the PC boots" work.
The phone is passive; the PC does all four steps:

  1. wait for the device to appear on USB
  2. `adb reverse` so the phone's own localhost:8770 tunnels to ours
  3. wake the screen
  4. `am start` the shell app

A watchdog repeats this whenever the device disappears and comes back, so
unplugging the cable or rebooting the phone recovers on its own.
"""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .config import ADB, ANDROID_ACTIVITY, ANDROID_PACKAGE, PORT

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
POLL_SECONDS = 3.0


@dataclass
class DeviceState:
    """What the bridge currently believes about the phone."""
    serial: str | None = None
    status: str = "disconnected"   # disconnected | unauthorized | offline | ready
    reverse_ok: bool = False
    app_launched: bool = False
    last_error: str | None = None
    last_change: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "serial": self.serial,
            "status": self.status,
            "reverse_ok": self.reverse_ok,
            "app_launched": self.app_launched,
            "last_error": self.last_error,
            "last_change": self.last_change,
        }


def _adb(*args: str, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ADB, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )


def list_devices() -> list[tuple[str, str]]:
    """Return [(serial, status)] as adb reports them."""
    try:
        proc = _adb("devices")
    except (OSError, subprocess.TimeoutExpired):
        return []
    devices: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines()[1:]:
        line = line.strip()
        if not line or "\t" not in line:
            continue
        serial, status = line.split("\t", 1)
        devices.append((serial.strip(), status.strip()))
    return devices


def setup_reverse(serial: str, port: int = PORT) -> bool:
    """Tunnel the device's localhost:PORT to ours, over the USB cable.

    This is what lets the phone talk to the server with no IP address, no
    Wi-Fi, and no exposure to anything else on the network.
    """
    try:
        proc = _adb("-s", serial, "reverse", f"tcp:{port}", f"tcp:{port}")
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def wake_device(serial: str) -> None:
    """Turn the screen on and dismiss a swipe-only keyguard."""
    try:
        # KEYCODE_WAKEUP is idempotent: it will not toggle an already-on screen
        # off, unlike KEYCODE_POWER.
        _adb("-s", serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
        _adb("-s", serial, "shell", "wm", "dismiss-keyguard")
    except (OSError, subprocess.TimeoutExpired):
        pass


def launch_app(serial: str, activity: str = ANDROID_ACTIVITY) -> bool:
    try:
        proc = _adb("-s", serial, "shell", "am", "start", "-n", activity)
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0 and "Error" not in out
    except (OSError, subprocess.TimeoutExpired):
        return False


def is_app_installed(serial: str, package: str = ANDROID_PACKAGE) -> bool:
    try:
        proc = _adb("-s", serial, "shell", "pm", "list", "packages", package)
        return package in (proc.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def stay_awake(serial: str) -> None:
    """Keep the screen on while charging, so the dashboard is always visible."""
    try:
        # 7 == AC | USB | wireless. Survives reboots; set once per connection
        # in case the phone has been factory-reset or the setting was cleared.
        _adb("-s", serial, "shell", "settings", "put", "global",
             "stay_on_while_plugged_in", "7")
    except (OSError, subprocess.TimeoutExpired):
        pass


class Bridge:
    """Background watchdog that keeps the phone connected and showing the app."""

    def __init__(self, *, auto_launch: bool = True, port: int = PORT) -> None:
        self.state = DeviceState()
        self.auto_launch = auto_launch
        self.port = port
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # -------------------------------------------------------------- api ----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="adb-bridge",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.state.as_dict()

    def relaunch(self) -> dict[str, Any]:
        """Force a wake + launch now, for the dashboard's 'reconnect' button."""
        with self._lock:
            serial = self.state.serial
            status = self.state.status
        if not serial or status != "ready":
            return {"ok": False, "message": f"device not ready ({status})"}
        wake_device(serial)
        ok = launch_app(serial)
        with self._lock:
            self.state.app_launched = ok
        return {"ok": ok, "message": "app launched" if ok else "launch failed"}

    # ------------------------------------------------------------- loop ----
    def _set(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self.state, key, value)
            self.state.last_change = time.time()

    def _loop(self) -> None:
        known_serial: str | None = None
        while not self._stop.is_set():
            devices = list_devices()

            if not devices:
                if known_serial is not None:
                    known_serial = None
                self._set(serial=None, status="disconnected",
                          reverse_ok=False, app_launched=False)
                self._stop.wait(POLL_SECONDS)
                continue

            serial, status = devices[0]

            if status == "unauthorized":
                self._set(
                    serial=serial, status="unauthorized",
                    reverse_ok=False, app_launched=False,
                    last_error="Accept the USB debugging prompt on the phone "
                               "and tick 'Always allow from this computer'.",
                )
                known_serial = None
                self._stop.wait(POLL_SECONDS)
                continue

            if status != "device":
                self._set(serial=serial, status=status or "offline",
                          reverse_ok=False, app_launched=False)
                known_serial = None
                self._stop.wait(POLL_SECONDS)
                continue

            # Freshly connected (or reconnected): run the full setup once.
            if serial != known_serial:
                known_serial = serial
                reverse_ok = setup_reverse(serial, self.port)
                stay_awake(serial)

                launched = False
                error = None
                if self.auto_launch:
                    if is_app_installed(serial):
                        wake_device(serial)
                        launched = launch_app(serial)
                        if not launched:
                            error = "app is installed but would not start"
                    else:
                        error = (f"{ANDROID_PACKAGE} is not installed on the "
                                 f"device yet")

                self._set(serial=serial, status="ready", reverse_ok=reverse_ok,
                          app_launched=launched, last_error=error)
            else:
                # Steady state. The reverse tunnel is the one thing that can
                # quietly drop, so re-assert it; adb treats it as idempotent.
                if not self.state.reverse_ok:
                    self._set(reverse_ok=setup_reverse(serial, self.port))

            self._stop.wait(POLL_SECONDS)
