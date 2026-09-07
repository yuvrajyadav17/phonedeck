"""Claude activity tracker.

Feeds the status light in the top bar. Two sources, combined:

* **Which sessions exist** comes from Claude's own registry in
  ``~/.claude/sessions``, one JSON file per live session. This is what makes
  the light correct the instant Claude is opened and after PhoneDeck restarts
  -- a session that is merely sitting idle has sent no events, and a purely
  event-driven tracker would call that "off", which is backwards.

* **What each session is doing** comes from Claude Code's hooks, which POST
  their event JSON straight to PhoneDeck. Only infrequent events are hooked --
  prompt submitted, notification, permission request, stop, failure, session
  start and end. PreToolUse/PostToolUse would fire on every tool call and add
  latency to each for nothing, since "running" already persists from the prompt
  until the stop.

There is no usage or limit reporting here. Claude Code's session and weekly
percentages come from the API, are written nowhere on disk, and have no CLI
equivalent, so they cannot be read from outside Claude.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("phonedeck.claude")

CLAUDE_DIR = Path(os.path.expanduser("~")) / ".claude"
SESSIONS_DIR = CLAUDE_DIR / "sessions"

# A turn claiming to be running for this long has almost certainly ended
# without us hearing about it (Claude killed, machine slept).
RUNNING_STALE_SECONDS = 60 * 60
# How long a session may be absent from Claude's registry before we drop it.
SESSION_GRACE_SECONDS = 30

# What each state means, and the colour its LED takes.
STATE_STYLE = {
    "offline":  {"label": "off",     "colour": "#5f7188"},
    "idle":     {"label": "idle",    "colour": "#38b48b"},
    "running":  {"label": "working", "colour": "#4c8dff"},
    "waiting":  {"label": "asking",  "colour": "#f0a94c"},
    "error":    {"label": "error",   "colour": "#e2617a"},
    "limit":    {"label": "limit",   "colour": "#b57bee"},
}

# Most important first: if any session needs you, that is what the light shows.
STATE_PRIORITY = ["waiting", "limit", "error", "running", "idle", "offline"]

_EVENT_STATE = {
    "SessionStart": "idle",
    "UserPromptSubmit": "running",
    "Notification": "waiting",
    "PermissionRequest": "waiting",
    "Elicitation": "waiting",
    "Stop": "idle",
    "StopFailure": "error",
    "SessionEnd": "offline",
}

LIMIT_WORDS = ("usage limit", "rate limit", "rate_limit", "quota",
               "limit reached", "too many requests", "429")


def _looks_like_limit(text: str) -> bool:
    low = text.lower()
    return any(word in low for word in LIMIT_WORDS)


def _last_api_error(transcript_path: str | None, lines: int = 40) -> str | None:
    """Most recent API error in a transcript.

    Used to tell an ordinary failure apart from hitting a usage limit, which
    the StopFailure event itself does not distinguish.
    """
    if not transcript_path:
        return None
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = min(size, 256 * 1024)
            fh.seek(size - block)
            tail = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for line in reversed(tail[-lines:]):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not rec.get("isApiErrorMessage"):
            continue
        content = (rec.get("message") or {}).get("content")
        if isinstance(content, list):
            return " ".join(part.get("text", "") for part in content
                            if isinstance(part, dict))
        if isinstance(content, str):
            return content
    return None


def live_session_ids() -> set[str] | None:
    """Session ids Claude Code currently has running, from its own registry.

    Returns None if the registry cannot be read, in which case nothing is
    pruned and nothing is seeded.
    """
    if not SESSIONS_DIR.is_dir():
        return None
    try:
        import psutil
    except ImportError:
        return None

    try:
        entries = list(SESSIONS_DIR.glob("*.json"))
    except OSError:
        return None

    live: set[str] = set()
    for path in entries:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        session_id = record.get("sessionId")
        pid = record.get("pid")
        if not session_id or not isinstance(pid, int):
            continue
        try:
            if psutil.pid_exists(pid):
                live.add(str(session_id))
        except Exception:  # noqa: BLE001
            live.add(str(session_id))  # assume alive if we cannot tell
    return live


class Tracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def handle_event(self, payload: dict[str, Any]) -> None:
        event = str(payload.get("hook_event_name") or "")
        state = _EVENT_STATE.get(event)
        if state is None:
            return

        session_id = str(payload.get("session_id") or "unknown")
        detail = None

        if state == "error":
            message = _last_api_error(payload.get("transcript_path"))
            if message and _looks_like_limit(message):
                state = "limit"
            detail = (message or "")[:140] or None

        if state == "offline":
            with self._lock:
                self._sessions.pop(session_id, None)
            return

        with self._lock:
            self._sessions[session_id] = {
                "state": state,
                "since": time.time(),
                "cwd": payload.get("cwd"),
                "detail": detail,
                "event": event,
            }

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            sessions = dict(self._sessions)

        live = live_session_ids()
        if live is not None:
            # Forget sessions Claude is no longer running. The grace period
            # avoids pruning one that has only just started and is not yet in
            # the registry.
            dead = [sid for sid, info in sessions.items()
                    if sid not in live and now - info["since"] > SESSION_GRACE_SECONDS]
            if dead:
                with self._lock:
                    for sid in dead:
                        self._sessions.pop(sid, None)
                for sid in dead:
                    sessions.pop(sid, None)

            # Seed sessions we know are open but have heard nothing from.
            for sid in live:
                if sid not in sessions:
                    sessions[sid] = {"state": "idle", "since": now,
                                     "cwd": None, "detail": None,
                                     "event": "registry"}

        active: list[dict[str, Any]] = []
        for info in sessions.values():
            if info["state"] == "running" and now - info["since"] > RUNNING_STALE_SECONDS:
                info = {**info, "state": "idle"}
            active.append(info)

        state = "offline"
        detail = None
        for candidate in STATE_PRIORITY:
            match = next((i for i in active if i["state"] == candidate), None)
            if match:
                state = candidate
                detail = match.get("detail")
                break

        style = STATE_STYLE[state]
        return {
            "state": state,
            "label": style["label"],
            "colour": style["colour"],
            "sessions": len(active),
            "detail": detail,
            "since": max((i["since"] for i in active), default=None),
        }


tracker = Tracker()
