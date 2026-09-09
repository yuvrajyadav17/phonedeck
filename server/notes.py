"""Notes and to-dos.

Deliberately a flat list of lines. Editing happens on the PC in a plain
textarea -- one line, one item -- because typing on a phone taped to a desk is
miserable and a real keyboard is already right there. The phone's job is to
*show* the list and to tick things off, which is the part worth doing by touch.

Stored in .state/notes.json rather than beside shortcuts.json: this is personal
content, and .state is gitignored, so notes never end up in the repository.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from .config import STATE_DIR

NOTES_FILE = STATE_DIR / "notes.json"

_lock = threading.Lock()


def _new_item(text: str) -> dict[str, Any]:
    return {"id": uuid.uuid4().hex[:12], "text": text, "created": time.time()}


def load() -> dict[str, Any]:
    with _lock:
        try:
            data = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"items": []}
    items = data.get("items")
    return {"items": items if isinstance(items, list) else []}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = NOTES_FILE.with_suffix(".json.tmp")
    with _lock:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        tmp.replace(NOTES_FILE)


def as_text() -> str:
    """The list as plain lines, for the editor window."""
    return "\n".join(item.get("text", "") for item in load()["items"])


def from_text(text: str) -> dict[str, Any]:
    """Replace the list from edited plain text, one item per line.

    Ids are carried over for lines whose text is unchanged, so ticking
    something off on the phone while the editor is open cannot silently
    resurrect it under a new id.
    """
    existing = {item.get("text"): item for item in load()["items"]}
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        items.append(existing.get(line) or _new_item(line))

    data = {"items": items}
    _save(data)
    return data


def add(text: str) -> dict[str, Any]:
    line = text.strip()
    if not line:
        return load()
    data = load()
    data["items"].append(_new_item(line))
    _save(data)
    return data


def remove(item_id: str) -> bool:
    """Tick something off. Done means gone -- there is no archive by design."""
    data = load()
    before = len(data["items"])
    data["items"] = [i for i in data["items"] if i.get("id") != item_id]
    if len(data["items"]) == before:
        return False
    _save(data)
    return True
