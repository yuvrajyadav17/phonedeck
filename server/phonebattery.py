"""Watch the phone's own battery, and keep a record of it.

The worry this answers: a phone left plugged in permanently sits at 100% and
warm, and a lithium cell held full and warm swells eventually. The obvious
fix -- tell the phone to run from USB and leave the battery alone -- is not
available here. On the CPH1859 the kernel does expose the right switches:

    /sys/class/power_supply/battery/mmi_charging_enable    rw- root root
    /sys/class/power_supply/battery/stop_charging_enable   rw- root root

but adb runs as uid 2000 (`shell`), the bootloader is locked and there is no
`su`, so writing either one is a straight permission denial. `dumpsys battery
unplug` looks promising and is not: it flips the framework's idea of being
plugged in, while the charger IC carries on regardless -- measured, the
current stayed at +70 mA with the framework reporting "USB powered: false".

So instead of guessing, measure. This samples the phone once a minute and
keeps a CSV, because the question "does it actually sit at 100%?" is answered
by a day of data and not by an opinion. The first readings were encouraging:
the port supplies 500 mA, the dashboard with the screen on draws more, and
the level sat at 76% with the current swinging either side of zero -- a phone
that never fills is a phone that is not being held full.
"""
from __future__ import annotations

import csv
import logging
import re
import subprocess
import threading
import time
from typing import Any, Callable

from .config import ADB, STATE_DIR

log = logging.getLogger("phonedeck.battery")

INTERVAL = 60.0
# The bridge needs a few seconds to find the phone, so the first reading is
# retried quickly rather than waiting out a whole minute for nothing.
STARTUP_INTERVAL = 5.0
LOG_FILE = STATE_DIR / "battery.csv"
MAX_BYTES = 5 * 1024 * 1024
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

FIELDS = ("time", "level", "status", "temp_c", "current_ma", "plugged")

# Android reports these as small integers; the names are worth more than the
# numbers to anyone reading the CSV later.
STATUS = {1: "unknown", 2: "charging", 3: "discharging",
          4: "not charging", 5: "full"}


def _read(serial: str) -> dict[str, Any] | None:
    """One reading, or None if the phone did not answer."""
    try:
        proc = subprocess.run([ADB, "-s", serial, "shell", "dumpsys", "battery"],
                              capture_output=True, text=True, timeout=15,
                              creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None

    def find(pattern: str) -> int | None:
        m = re.search(pattern + r"\s*:\s*(-?\d+)", proc.stdout,
                      re.I | re.M)
        return int(m.group(1)) if m else None

    level = find(r"^\s*level")
    if level is None:
        return None
    status = find(r"^\s*status")
    temp = find(r"^\s*temperature")
    return {
        "time": round(time.time()),
        "level": level,
        "status": STATUS.get(status or 0, str(status)),
        # Reported in tenths of a degree.
        "temp_c": round(temp / 10, 1) if temp is not None else None,
        # Positive is into the battery, negative is out of it. On this device
        # it swings both ways while plugged in, which is the whole point.
        "current_ma": find(r"Battery current"),
        "plugged": bool(re.search(r"USB powered\s*:\s*true", proc.stdout, re.I)
                        or re.search(r"AC powered\s*:\s*true", proc.stdout, re.I)),
    }


class PhoneBattery:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, Any] | None = None
        self._started = False

    def start(self, get_serial: Callable[[], str | None]) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._loop, args=(get_serial,),
                         name="phone-battery", daemon=True).start()

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return self._latest

    def _loop(self, get_serial: Callable[[], str | None]) -> None:
        while True:
            try:
                serial = get_serial()
                if serial:
                    reading = _read(serial)
                    if reading:
                        with self._lock:
                            self._latest = reading
                        self._append(reading)
            except Exception:  # noqa: BLE001 - a phone unplugged mid-read
                log.exception("battery sample failed")
            time.sleep(INTERVAL if self._latest else STARTUP_INTERVAL)

    def _append(self, reading: dict[str, Any]) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_BYTES:
            LOG_FILE.replace(LOG_FILE.with_suffix(".csv.old"))
        new = not LOG_FILE.exists()
        with LOG_FILE.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                writer.writeheader()
            writer.writerow({k: reading.get(k) for k in FIELDS})


def summarise() -> dict[str, Any]:
    """What the log says so far -- the answer to "is it sitting at 100%?"."""
    if not LOG_FILE.exists():
        return {"samples": 0}
    levels: list[int] = []
    temps: list[float] = []
    high = 0
    first = last = None
    with LOG_FILE.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                level = int(row["level"])
            except (TypeError, ValueError):
                continue
            levels.append(level)
            if level >= 90:
                high += 1
            if row.get("temp_c"):
                try:
                    temps.append(float(row["temp_c"]))
                except ValueError:
                    pass
            first = first or row.get("time")
            last = row.get("time")
    if not levels:
        return {"samples": 0}
    span = None
    if first and last:
        span = round((int(last) - int(first)) / 3600, 1)
    return {
        "samples": len(levels),
        "hours_logged": span,
        "level_min": min(levels),
        "level_max": max(levels),
        "level_now": levels[-1],
        # The number that decides whether any of this matters.
        "percent_of_time_at_90_plus": round(high / len(levels) * 100, 1),
        "temp_mean_c": round(sum(temps) / len(temps), 1) if temps else None,
        "temp_max_c": max(temps) if temps else None,
    }


phone_battery = PhoneBattery()
