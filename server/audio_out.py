"""Stream what the PC is playing to the phone's speaker.

Captures the default output device with WASAPI loopback -- the same trick a
recorder uses to "record what you hear" -- downmixes to mono, and hands raw
16-bit PCM to whoever is listening on the WebSocket.

Three deliberate choices:

* **Mono, not stereo.** The phone has a single loudspeaker, so a second channel
  would be thrown away at the other end. Downmixing here halves the bandwidth.
* **Raw PCM, no codec.** The link is a USB cable, where 768 kbps is nothing.
  An encoder would only add latency and a dependency.
* **Capture only while someone is listening.** Loopback capture holds an audio
  client open and costs CPU; there is no reason to run it into an empty room.

Latency is roughly the jitter buffer on the phone plus the block size here --
about a fifth of a second. Fine for music, poor for lip-sync on video.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

import numpy as np

log = logging.getLogger("phonedeck.audio")

RATE = 48000
BLOCK = 1024          # frames per capture block, ~21 ms
CHANNELS = 2

# If a listener cannot keep up, drop rather than grow without bound: stale
# audio is worse than a gap.
MAX_QUEUED_BLOCKS = 24

# How often to notice that the default output device changed.
DEVICE_CHECK_SECONDS = 2.0

try:
    import soundcard as sc
    AVAILABLE = True
except ImportError:  # pragma: no cover
    sc = None  # type: ignore[assignment]
    AVAILABLE = False


class AudioOut:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: set[queue.Queue] = set()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._device_name: str | None = None
        self._frames_sent = 0

    # ------------------------------------------------------- listeners ----
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=MAX_QUEUED_BLOCKS)
        with self._lock:
            self._listeners.add(q)
            first = len(self._listeners) == 1
        if first:
            self._start()
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._listeners.discard(q)
            last = not self._listeners
        if last:
            self._stop.set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            listeners = len(self._listeners)
        return {
            "available": AVAILABLE,
            "listeners": listeners,
            "streaming": listeners > 0,
            "device": self._device_name,
            "rate": RATE,
        }

    # --------------------------------------------------------- capture ----
    def _start(self) -> None:
        if not AVAILABLE:
            log.warning("soundcard is not installed; audio streaming disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="audio-out",
                                        daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._capture()
            except Exception:  # noqa: BLE001 - a device change must not kill it
                log.exception("audio capture stopped; retrying")
                time.sleep(1.0)

    def _capture(self) -> None:
        speaker = sc.default_speaker()
        self._device_name = str(speaker.name)
        log.info("streaming audio from %s", self._device_name)

        mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        next_device_check = time.monotonic() + DEVICE_CHECK_SECONDS

        with mic.recorder(samplerate=RATE, channels=CHANNELS,
                          blocksize=BLOCK) as rec:
            while not self._stop.is_set():
                block = rec.record(numframes=BLOCK)

                # Downmix and convert once here rather than per listener.
                mono = block.mean(axis=1)
                pcm = np.clip(mono * 32767.0, -32768, 32767).astype("<i2").tobytes()
                self._frames_sent += len(mono)

                with self._lock:
                    listeners = list(self._listeners)
                for q in listeners:
                    try:
                        q.put_nowait(pcm)
                    except queue.Full:
                        # This listener is behind; drop the block for it alone.
                        pass

                # The default device can change under us (headphones plugged
                # in). Notice and reopen -- but only occasionally: querying it
                # per block, sixty times a second, would cost more than the
                # capture itself.
                now = time.monotonic()
                if now >= next_device_check:
                    next_device_check = now + DEVICE_CHECK_SECONDS
                    if str(sc.default_speaker().name) != self._device_name:
                        log.info("output device changed; reopening")
                        return

        self._device_name = None


audio_out = AudioOut()
