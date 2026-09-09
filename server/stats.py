"""System telemetry -- the Task Manager view the phone shows by default.

Sampling is stateful on purpose: CPU percentages and network throughput are
both rates, meaningless from a single reading. We keep the previous sample and
report the delta, so the first call after startup returns zeroed rates and
every call after that is accurate.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import psutil

from . import claude, downloads, notes, nowplaying, procscan, sensors, weather

_BOOT_TIME = psutil.boot_time()
_LOGICAL_CORES = psutil.cpu_count(logical=True) or 1


def _cpu_model() -> str:
    """The marketing name, e.g. "Intel(R) Core(TM) Ultra 7 265K".

    Read once from the registry: platform.processor() returns the family and
    stepping on Windows, which is not what anyone wants on a dashboard, and a
    WMI query would mean spawning a process.
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        with key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (ImportError, OSError):
        import platform
        return platform.processor() or "CPU"


_CPU_MODEL = _cpu_model()

# We deliberately do NOT use psutil.cpu_percent(interval=None). It stores its
# "previous sample" keyed by thread id, and the web server hands every request
# to a fresh thread -- so every call looks like a first call and reports 0.0.
# Tracking the delta ourselves is both correct under threading and consistent
# with how network and disk rates are computed below.
_sample_lock = threading.Lock()
_prev_cpu_times: Any = None
_prev_cpu_times_percpu: list[Any] | None = None
_prev_net: tuple[float, int, int] | None = None
_prev_disk: tuple[float, int, int] | None = None


def _human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} PB"


def _busy_percent(before: Any, after: Any) -> float:
    """Percentage of a CPU's time spent doing anything but idling.

    Mirrors psutil's own arithmetic so the numbers match what psutil would
    report -- total time across every bucket, minus the idle bucket.
    """
    total_delta = sum(after) - sum(before)
    if total_delta <= 0:
        return 0.0
    busy_delta = total_delta - (after.idle - before.idle)
    return round(max(0.0, min(100.0, busy_delta / total_delta * 100.0)), 1)


def _cpu() -> dict[str, Any]:
    global _prev_cpu_times, _prev_cpu_times_percpu

    now_total = psutil.cpu_times()
    now_per_core = psutil.cpu_times(percpu=True)

    with _sample_lock:
        prev_total = _prev_cpu_times
        prev_per_core = _prev_cpu_times_percpu
        _prev_cpu_times = now_total
        _prev_cpu_times_percpu = now_per_core

    if prev_total is None:
        overall = 0.0
        per_core = [0.0] * len(now_per_core)
    else:
        overall = _busy_percent(prev_total, now_total)
        per_core = [
            _busy_percent(old, new)
            for old, new in zip(prev_per_core or [], now_per_core)
        ]

    freq = psutil.cpu_freq()
    return {
        "name": _CPU_MODEL,
        "percent": overall,
        "per_core": per_core,
        "cores_physical": psutil.cpu_count(logical=False),
        "cores_logical": _LOGICAL_CORES,
        "freq_mhz": round(freq.current) if freq else None,
        "freq_max_mhz": round(freq.max) if freq and freq.max else None,
    }


def _memory() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    return {
        "percent": vm.percent,
        "used": vm.used,
        "total": vm.total,
        "available": vm.available,
        "used_h": _human_bytes(vm.used),
        "total_h": _human_bytes(vm.total),
        "swap_percent": sm.percent,
        "swap_used_h": _human_bytes(sm.used),
        "swap_total_h": _human_bytes(sm.total),
    }


def _disks() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for part in psutil.disk_partitions(all=False):
        # Empty optical/card readers raise on Windows; skip rather than fail
        # the whole stats payload for one unreadable drive.
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        out.append({
            "device": part.device.rstrip("\\"),
            "mount": part.mountpoint,
            "fstype": part.fstype,
            "percent": usage.percent,
            "used_h": _human_bytes(usage.used),
            "total_h": _human_bytes(usage.total),
            "free_h": _human_bytes(usage.free),
        })
    return out


def _disk_io() -> dict[str, Any]:
    global _prev_disk
    io = psutil.disk_io_counters()
    now = time.monotonic()
    if io is None:
        return {"read_per_s": 0, "write_per_s": 0,
                "read_per_s_h": "0 B/s", "write_per_s_h": "0 B/s"}

    read_rate = write_rate = 0.0
    if _prev_disk is not None:
        prev_t, prev_r, prev_w = _prev_disk
        elapsed = now - prev_t
        if elapsed > 0:
            read_rate = max(0.0, (io.read_bytes - prev_r) / elapsed)
            write_rate = max(0.0, (io.write_bytes - prev_w) / elapsed)
    _prev_disk = (now, io.read_bytes, io.write_bytes)
    return {
        "read_per_s": read_rate,
        "write_per_s": write_rate,
        "read_per_s_h": _human_bytes(read_rate) + "/s",
        "write_per_s_h": _human_bytes(write_rate) + "/s",
    }


def _network() -> dict[str, Any]:
    global _prev_net
    io = psutil.net_io_counters()
    now = time.monotonic()

    up_rate = down_rate = 0.0
    if _prev_net is not None:
        prev_t, prev_sent, prev_recv = _prev_net
        elapsed = now - prev_t
        if elapsed > 0:
            up_rate = max(0.0, (io.bytes_sent - prev_sent) / elapsed)
            down_rate = max(0.0, (io.bytes_recv - prev_recv) / elapsed)
    _prev_net = (now, io.bytes_sent, io.bytes_recv)

    return {
        "up_per_s": up_rate,
        "down_per_s": down_rate,
        "up_per_s_h": _human_bytes(up_rate) + "/s",
        "down_per_s_h": _human_bytes(down_rate) + "/s",
        "total_sent_h": _human_bytes(io.bytes_sent),
        "total_recv_h": _human_bytes(io.bytes_recv),
    }


def _battery() -> dict[str, Any] | None:
    try:
        bat = psutil.sensors_battery()
    except (AttributeError, NotImplementedError):
        return None
    if bat is None:
        return None
    return {
        "percent": round(bat.percent),
        "plugged": bat.power_plugged,
        "secs_left": bat.secsleft if bat.secsleft not in (
            psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else None,
    }


def _uptime() -> dict[str, Any]:
    seconds = int(time.time() - _BOOT_TIME)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    # The top bar shows a running hh:mm:ss clock; days are folded into the
    # hours so it stays a single stable-width field.
    clock = f"{days * 24 + hours:02d}:{minutes:02d}:{seconds % 60:02d}"
    return {"seconds": seconds, "text": " ".join(parts), "clock": clock}


def snapshot(include_processes: bool = True) -> dict[str, Any]:
    """One complete reading of the machine, ready to serialise as JSON."""
    external = sensors.snapshot()
    claude_state = claude.tracker.snapshot()
    data: dict[str, Any] = {
        "time": time.time(),
        "cpu": _cpu(),
        "memory": _memory(),
        "disks": _disks(),
        "disk_io": _disk_io(),
        "network": _network(),
        "uptime": _uptime(),
        "battery": _battery(),
        # Sampled on a background thread; see sensors.py for why.
        "gpu": external["gpu"],
        "temps": external["temps"],
        "claude": claude_state,
        "weather": weather.weather.snapshot(),
        "now_playing": nowplaying.now_playing.snapshot(),
        "notes": notes.load()["items"],
        "downloads": downloads.downloads.snapshot(),
    }
    if include_processes:
        # Scanned in a child process, on its own cadence; see procscan.py for
        # why it cannot be done here.
        data["processes"] = procscan.scanner.snapshot()
    return data
