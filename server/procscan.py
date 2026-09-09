"""The process table, scanned in a process of its own.

Walking Windows' process list is not slow because Python is slow. It is slow
because psutil's ``proc_info`` is a C call that takes about five milliseconds
per process and does not release the GIL while it runs. Three hundred
processes is over a second during which no other thread in the interpreter can
run at all -- including the one feeding audio to the phone, which is why the
stream arrived in bursts of a hundred and fifty milliseconds instead of a
steady forty-three.

Threads cannot fix that; a thread blocked in a C call that holds the GIL blocks
everything. A second interpreter can, because it has a GIL of its own. So the
scan runs in a child process on its own unhurried schedule and reports back
over a pipe, and the server thread that answers the dashboard simply reads the
most recent answer.

This also makes the CPU figures better rather than worse. psutil reports usage
since the same process object was last polled, so a fixed two-second cadence
gives a real interval to divide by instead of however long the phone happened
to take between requests.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any

import psutil

log = logging.getLogger("phonedeck.procscan")

INTERVAL = 2.0
LIMIT = 20
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EMPTY: dict[str, list[dict[str, Any]]] = {"by_cpu": [], "by_mem": []}


def _human_bytes(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def scan(cores: int, limit: int = LIMIT) -> dict[str, list[dict[str, Any]]]:
    """Busiest processes by CPU, with memory as the tiebreaker."""
    procs: list[dict[str, Any]] = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
        try:
            info = p.info
            pid = info["pid"]
            # PID 0 is the System Idle Process: it is not a task, and its
            # "usage" is whatever the machine is *not* doing. Task Manager
            # hides it and so do we, or it permanently tops the list.
            if pid == 0:
                continue
            mem = info.get("memory_info")
            # psutil reports CPU summed across cores, so a single busy thread
            # on a 20-thread box reads 100%. Divide by the core count to get
            # the share-of-machine figure Task Manager shows.
            procs.append({
                "pid": pid,
                "name": info.get("name") or "?",
                "cpu": round((info.get("cpu_percent") or 0.0) / cores, 1),
                "mem": mem.rss if mem else 0,
                "mem_h": _human_bytes(mem.rss) if mem else "0 B",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # The dashboard offers a CPU tab and a RAM tab, and the heaviest processes
    # by one measure are frequently not the heaviest by the other. Sorting the
    # same snapshot twice is far cheaper than walking the table again.
    by_cpu = sorted(procs, key=lambda x: (x["cpu"], x["mem"]), reverse=True)
    by_mem = sorted(procs, key=lambda x: (x["mem"], x["cpu"]), reverse=True)
    return {"by_cpu": by_cpu[:limit], "by_mem": by_mem[:limit]}


# --------------------------------------------------------------- parent ----
class Scanner:
    """Keeps the child alive and holds its most recent answer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, list[dict[str, Any]]] = EMPTY
        self._stamp = 0.0
        self._proc: subprocess.Popen[str] | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._supervise, name="procscan",
                         daemon=True).start()

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            return self._latest

    def status(self) -> dict[str, Any]:
        with self._lock:
            age = time.time() - self._stamp if self._stamp else None
        alive = bool(self._proc and self._proc.poll() is None)
        return {"running": alive, "age": round(age, 1) if age else None}

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()

    def _supervise(self) -> None:
        while True:
            try:
                self._run_child()
            except Exception:  # noqa: BLE001 - never take the server with it
                log.exception("process scanner died; restarting")
            time.sleep(2.0)

    def _run_child(self) -> None:
        # -u so lines arrive as they are written rather than when a pipe
        # buffer happens to fill.
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "server.procscan"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", creationflags=NO_WINDOW)
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            with self._lock:
                self._latest = data
                self._stamp = time.time()


scanner = Scanner()


def main() -> None:
    cores = psutil.cpu_count(logical=True) or 1
    scan(cores)          # prime psutil's per-process CPU baselines
    while True:
        time.sleep(INTERVAL)
        try:
            print(json.dumps(scan(cores)), flush=True)
        except (BrokenPipeError, OSError):
            return       # the server went away


if __name__ == "__main__":
    main()
