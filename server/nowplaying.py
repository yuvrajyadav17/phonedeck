"""What the PC is currently playing.

Reads Windows' own media session -- the same source the volume flyout uses --
so it works for anything that registers a session: Spotify, a browser tab,
VLC, the Media Player app. No per-application integration.

The API is WinRT and async, so a background thread owns an event loop and
refreshes into a cache. Requests read the cache and never wait.

Needs the split winrt packages (winrt-runtime plus
winrt-Windows.Media.Control). The older monolithic `winsdk` has no wheel for
Python 3.14 and fails to build. If the import fails this degrades to reporting
nothing rather than breaking the dashboard.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

log = logging.getLogger("phonedeck.nowplaying")

REFRESH_SECONDS = 2.0

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    )
    AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the machine
    SessionManager = None  # type: ignore[assignment]
    AVAILABLE = False

# GlobalSystemMediaTransportControlsSessionPlaybackStatus
STATUS = {0: "closed", 1: "opened", 2: "changing", 3: "stopped",
          4: "playing", 5: "paused"}


async def _read_session() -> dict[str, Any] | None:
    manager = await SessionManager.request_async()
    session = manager.get_current_session()
    if session is None:
        return None

    properties = await session.try_get_media_properties_async()
    playback = session.get_playback_info()
    status = STATUS.get(int(playback.playback_status), "unknown")

    title = (properties.title or "").strip()
    artist = (properties.artist or "").strip()
    if not title and not artist:
        return None

    # The owning app id looks like "Spotify.exe" or an AUMID; trim it to
    # something that fits a small panel.
    source = (session.source_app_user_model_id or "").split("!")[-1]
    if source.lower().endswith(".exe"):
        source = source[:-4]

    return {
        "title": title,
        "artist": artist,
        "album": (properties.album_title or "").strip(),
        "status": status,
        "playing": status == "playing",
        "source": source,
        "updated": time.time(),
    }


class NowPlaying:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Any] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not AVAILABLE:
            log.info("winrt media packages missing; now playing disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="now-playing",
                                        daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        # WinRT calls are async and need a loop; this thread owns one for its
        # whole life rather than creating one per poll.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            try:
                data = loop.run_until_complete(_read_session())
            except Exception:  # noqa: BLE001 - a media fault must not spread
                data = None
            with self._lock:
                self._data = data
            time.sleep(REFRESH_SECONDS)

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._data) if self._data else None


now_playing = NowPlaying()
