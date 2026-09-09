"""What is currently downloading.

Browsers write a partial file while a download is in flight and rename it when
it finishes -- Chromium family uses ".crdownload", Firefox ".part", Opera
".opdownload". Watching for those is a reliable, zero-configuration way to know
something is being fetched, without hooking into any browser.

Honest scope: this sees *browser* downloads into the watched folders. It will
not see Steam, a torrent client, winget, or anything else that writes
elsewhere or without a partial-file convention. Add folders to WATCH_DIRS if
you want more covered.

Total size is not knowable from a partial file, so there is no percentage --
what is reported is how much has arrived and how fast it is arriving, which is
what you actually want to know while waiting.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("phonedeck.downloads")

PARTIAL_SUFFIXES = {".crdownload", ".part", ".download", ".opdownload", ".!ut"}

WATCH_DIRS = [
    Path(os.path.expanduser("~")) / "Downloads",
]

POLL_SECONDS = 2.0
# A partial file that has not grown in this long is probably a paused or dead
# download, not an active one.
STALE_SECONDS = 90.0


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} PB"


class Downloads:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: list[dict[str, Any]] = []
        # path -> (last size, when seen), for working out the rate
        self._seen: dict[str, tuple[int, float]] = {}
        self._finished_at = 0.0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="downloads",
                                        daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            try:
                self._scan()
            except Exception:  # noqa: BLE001 - never take the panel down
                log.exception("download scan failed")
            time.sleep(POLL_SECONDS)

    def _scan(self) -> None:
        now = time.time()
        found: list[dict[str, Any]] = []
        current_paths: set[str] = set()

        for folder in WATCH_DIRS:
            if not folder.is_dir():
                continue
            try:
                entries = list(folder.iterdir())
            except OSError:
                continue

            for path in entries:
                if path.suffix.lower() not in PARTIAL_SUFFIXES:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue

                key = str(path)
                current_paths.add(key)
                previous = self._seen.get(key)
                self._seen[key] = (size, now)

                rate = 0.0
                growing = False
                if previous:
                    prev_size, prev_when = previous
                    elapsed = now - prev_when
                    if elapsed > 0 and size > prev_size:
                        rate = (size - prev_size) / elapsed
                        growing = True
                    elif size == prev_size and now - prev_when > STALE_SECONDS:
                        growing = False

                found.append({
                    "name": path.stem,          # strip the .crdownload part
                    "size": size,
                    "size_h": _human(size),
                    "rate": rate,
                    "rate_h": _human(rate) + "/s",
                    "growing": growing,
                    "folder": str(folder),
                })

        # A partial file that vanished finished (or was cancelled); either way
        # the transfer is over, which is worth announcing once.
        gone = [p for p in self._seen if p not in current_paths]
        for path in gone:
            del self._seen[path]
        if gone:
            self._finished_at = now

        found.sort(key=lambda d: d["rate"], reverse=True)
        with self._lock:
            self._active = found

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active = list(self._active)
            finished_at = self._finished_at
        total_rate = sum(d["rate"] for d in active)
        return {
            "count": len(active),
            "items": active,
            "total_rate": total_rate,
            "total_rate_h": _human(total_rate) + "/s",
            # Lets the phone chime once when a download completes.
            "finished_at": finished_at,
        }


downloads = Downloads()
