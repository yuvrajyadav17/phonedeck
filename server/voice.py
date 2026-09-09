"""Voice input: the phone's microphone as a dictation device for the PC.

The phone captures audio in the browser, streams 16 kHz mono PCM over a
WebSocket, and this recognises it offline with Vosk and types the result into
whatever window has focus -- reusing the same SendInput path as the hotkey
buttons.

Why type rather than expose a microphone device: making the phone appear as a
real Windows input device would need a virtual audio driver installed at kernel
level, with administrator rights and a reboot. Typing the recognised text needs
none of that and is what "voice input" is actually wanted for.

Recognition is offline. No audio leaves the machine, there is no API key, and
it works without internet.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from .config import ROOT

log = logging.getLogger("phonedeck.voice")

# 16 kHz mono is what the model expects; the phone resamples before sending.
RATE = 16000

MODEL_DIR = ROOT / ".tools" / "vosk-model-small-en-us-0.15"

try:
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)          # the C library is chatty on stderr otherwise
    AVAILABLE = True
except ImportError:  # pragma: no cover
    Model = KaldiRecognizer = None  # type: ignore[assignment]
    AVAILABLE = False


class Voice:
    """Holds the model once; each session gets its own recogniser."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model: Any = None
        self._error: str | None = None

    def status(self) -> dict[str, Any]:
        return {
            "available": AVAILABLE and MODEL_DIR.is_dir(),
            "model_present": MODEL_DIR.is_dir(),
            "package_present": AVAILABLE,
            "model_path": str(MODEL_DIR),
            "rate": RATE,
            "error": self._error,
        }

    def _load(self) -> Any:
        """Load the model on first use -- it takes a second and ~50 MB."""
        with self._lock:
            if self._model is not None:
                return self._model
            if not AVAILABLE:
                self._error = "the vosk package is not installed"
                return None
            if not MODEL_DIR.is_dir():
                self._error = f"no speech model at {MODEL_DIR}"
                return None
            log.info("loading speech model from %s", MODEL_DIR)
            self._model = Model(str(MODEL_DIR))
            self._error = None
            return self._model

    def session(self) -> "VoiceSession | None":
        model = self._load()
        if model is None:
            return None
        return VoiceSession(KaldiRecognizer(model, RATE))


class VoiceSession:
    """One run of dictation: feed it PCM, get phrases back."""

    def __init__(self, recogniser: Any) -> None:
        self._rec = recogniser
        self._rec.SetWords(False)

    def feed(self, pcm: bytes) -> dict[str, Any]:
        """Returns {'final': text} when a phrase completes, else a partial."""
        if self._rec.AcceptWaveform(pcm):
            text = json.loads(self._rec.Result()).get("text", "").strip()
            return {"final": text} if text else {}
        partial = json.loads(self._rec.PartialResult()).get("partial", "").strip()
        return {"partial": partial} if partial else {}

    def finish(self) -> str:
        """Whatever is left when the user stops talking."""
        return json.loads(self._rec.FinalResult()).get("text", "").strip()


voice = Voice()
