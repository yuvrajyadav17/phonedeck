"""Temperatures and GPU telemetry -- the things psutil cannot see on Windows.

Windows exposes no general temperature API to user space, so every value here
comes from an external provider. Each is probed independently and degrades to
None rather than failing:

  * GPU (NVIDIA)  -- nvidia-smi, shipped with the driver. Works out of the box.
  * CPU package   -- LibreHardwareMonitor, over its HTTP server or its WMI
                     provider. Nothing built into Windows reports it.

Everything is sampled on a background thread and read from cache, because
nvidia-smi costs a couple of hundred milliseconds per call and PowerShell far
more -- far too slow to sit in the path of a once-per-second dashboard poll.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# How often the background thread refreshes. Temperatures move slowly; there is
# nothing to gain from hammering the providers.
SAMPLE_SECONDS = 2.0
# After a provider is found missing, wait this long before probing it again.
RETRY_MISSING_SECONDS = 60.0

LHM_URL = "http://127.0.0.1:8085/data.json"


def _run(argv: list[str], timeout: float = 4.0) -> str | None:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


# ------------------------------------------------------------- NVIDIA GPU --
def _nvidia_smi_path() -> str | None:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    # The driver installs it here even when it is not on PATH.
    fallback = r"C:\Windows\System32\nvidia-smi.exe"
    return fallback if shutil.os.path.exists(fallback) else None


def _read_nvidia(path: str) -> dict[str, Any] | None:
    out = _run([
        path,
        "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,"
        "memory.total,power.draw,fan.speed",
        "--format=csv,noheader,nounits",
    ])
    if not out or not out.strip():
        return None

    # First GPU only; a second adapter is almost always the integrated one.
    fields = [f.strip() for f in out.strip().splitlines()[0].split(",")]
    if len(fields) < 6:
        return None

    def number(text: str) -> float | None:
        try:
            return float(text)
        except ValueError:
            return None  # nvidia-smi prints "[N/A]" for unsupported sensors

    used = number(fields[3])
    total = number(fields[4])
    return {
        "name": fields[0],
        "temp_c": number(fields[1]),
        "load_percent": number(fields[2]),
        "mem_used_mb": used,
        "mem_total_mb": total,
        "mem_percent": round(used / total * 100, 1) if used and total else None,
        "power_w": number(fields[5]),
        "fan_percent": number(fields[6]) if len(fields) > 6 else None,
    }


# ------------------------------------------------- LibreHardwareMonitor ----
def _walk_lhm(node: dict[str, Any], out: list[tuple[str, str]]) -> None:
    """Flatten LHM's nested tree into (label, value) pairs."""
    text = node.get("Text") or ""
    value = node.get("Value") or ""
    if value:
        out.append((text, value))
    for child in node.get("Children", []):
        _walk_lhm(child, out)


def _parse_temp(value: str) -> float | None:
    # LHM formats values like "42.5 \u00b0C"
    cleaned = value.replace("\u00b0", "").replace("C", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _read_lhm_http() -> dict[str, float] | None:
    """Read temperatures from LibreHardwareMonitor's built-in web server.

    Enable it in LHM under Options -> Remote Web Server -> Run.
    """
    try:
        with urllib.request.urlopen(LHM_URL, timeout=2.0) as fh:
            tree = json.load(fh)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None

    pairs: list[tuple[str, str]] = []
    _walk_lhm(tree, pairs)

    result: dict[str, float] = {}
    for label, value in pairs:
        low = label.lower()
        temp = _parse_temp(value)
        if temp is None or "\u00b0c" not in value.lower().replace(" ", ""):
            continue
        # "CPU Package" is the whole-die figure; "Core Max" is the next best.
        if "cpu package" in low and "cpu" not in result:
            result["cpu"] = temp
        elif "core max" in low and "cpu" not in result:
            result["cpu"] = temp
        elif "gpu core" in low and "gpu" not in result:
            result["gpu"] = temp
    return result or None


def _read_lhm_wmi() -> dict[str, float] | None:
    """Fallback: LibreHardwareMonitor's WMI provider, via PowerShell.

    Slower than the HTTP route (a whole PowerShell start-up), which is why it
    is only tried when the web server is not running.
    """
    script = (
        "$ErrorActionPreference='Stop';"
        "foreach ($ns in 'LibreHardwareMonitor','OpenHardwareMonitor') {"
        "  try {"
        "    $s = Get-CimInstance -Namespace \"root\\$ns\" -ClassName Sensor |"
        "         Where-Object { $_.SensorType -eq 'Temperature' } |"
        "         Select-Object Name, Value, Identifier;"
        "    if ($s) { $s | ConvertTo-Json -Compress; exit 0 }"
        "  } catch {}"
        "}"
    )
    out = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
               timeout=8.0)
    if not out or not out.strip():
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    if isinstance(data, dict):
        data = [data]

    result: dict[str, float] = {}
    for sensor in data:
        name = str(sensor.get("Name", "")).lower()
        ident = str(sensor.get("Identifier", "")).lower()
        value = sensor.get("Value")
        if not isinstance(value, (int, float)):
            continue
        if "/cpu/" in ident and ("package" in name or "core max" in name) \
                and "cpu" not in result:
            result["cpu"] = round(float(value), 1)
        elif "/gpu" in ident and "core" in name and "gpu" not in result:
            result["gpu"] = round(float(value), 1)
    return result or None


# ------------------------------------------------------------- sampler ----
class _Sampler:
    """Refreshes the external readings on a background thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gpu: dict[str, Any] | None = None
        self._temps: dict[str, Any] = {"cpu_c": None, "gpu_c": None,
                                       "cpu_source": None}
        self._thread: threading.Thread | None = None
        self._nvidia_path: str | None = None
        self._nvidia_checked_at = 0.0
        self._lhm_missing_since = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="sensors",
                                        daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            try:
                self._sample()
            except Exception:  # noqa: BLE001 - a sensor must never kill the app
                pass
            time.sleep(SAMPLE_SECONDS)

    def _sample(self) -> None:
        now = time.monotonic()

        # --- GPU via nvidia-smi -------------------------------------------
        if self._nvidia_path is None and now - self._nvidia_checked_at > RETRY_MISSING_SECONDS:
            self._nvidia_checked_at = now
            self._nvidia_path = _nvidia_smi_path()

        gpu = _read_nvidia(self._nvidia_path) if self._nvidia_path else None

        # --- temperatures --------------------------------------------------
        temps: dict[str, Any] = {"cpu_c": None, "gpu_c": None, "cpu_source": None}
        if gpu and gpu.get("temp_c") is not None:
            temps["gpu_c"] = gpu["temp_c"]

        lhm = _read_lhm_http()
        source = "LibreHardwareMonitor (web)"
        if lhm is None and now - self._lhm_missing_since > RETRY_MISSING_SECONDS:
            lhm = _read_lhm_wmi()
            source = "LibreHardwareMonitor (WMI)"
            if lhm is None:
                self._lhm_missing_since = now

        if lhm:
            if lhm.get("cpu") is not None:
                temps["cpu_c"] = lhm["cpu"]
                temps["cpu_source"] = source
            if temps["gpu_c"] is None and lhm.get("gpu") is not None:
                temps["gpu_c"] = lhm["gpu"]

        with self._lock:
            self._gpu = gpu
            self._temps = temps

    def read(self) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        with self._lock:
            return self._gpu, dict(self._temps)


_sampler = _Sampler()


def start() -> None:
    """Begin sampling. Safe to call more than once."""
    _sampler.start()


def snapshot() -> dict[str, Any]:
    """Latest cached GPU and temperature readings."""
    gpu, temps = _sampler.read()
    return {"gpu": gpu, "temps": temps}
