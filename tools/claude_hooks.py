"""Install or remove the Claude Code hooks that drive the status LED.

Adds HTTP hooks to ~/.claude/settings.json so Claude posts state changes to
PhoneDeck. Only low-frequency events are hooked -- prompt submitted,
notification, permission request, stop, failure, session start/end -- so no
latency is added to individual tool calls.

    python tools/claude_hooks.py --install
    python tools/claude_hooks.py --remove
    python tools/claude_hooks.py --status

The previous settings file is backed up next to itself before any change.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

SETTINGS = Path(os.path.expanduser("~")) / ".claude" / "settings.json"
HOOK_URL = "http://127.0.0.1:8770/api/claude/hook"

# Marks our entries so they can be removed again without touching anyone
# else's hooks.
TAG = "phonedeck"

EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "Notification",
    "PermissionRequest",
    "Elicitation",
    "Stop",
    "StopFailure",
    "SessionEnd",
]


def hook_entry() -> dict:
    return {
        "type": "http",
        "url": HOOK_URL,
        # Short: if PhoneDeck is not running the connection is refused
        # immediately, and Claude should never wait on a status light.
        "timeout": 5,
        "statusMessage": TAG,
    }


def load() -> dict:
    if not SETTINGS.exists():
        return {}
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except ValueError as exc:
        sys.exit(f"{SETTINGS} is not valid JSON ({exc}); fix it before running this")


def save(data: dict) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    if SETTINGS.exists():
        backup = SETTINGS.with_suffix(f".json.bak-{int(time.time())}")
        shutil.copy2(SETTINGS, backup)
        print(f"backed up existing settings to {backup.name}")
    SETTINGS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def is_ours(hook: dict) -> bool:
    return (hook.get("type") == "http"
            and (hook.get("url") == HOOK_URL or hook.get("statusMessage") == TAG))


def install() -> None:
    data = load()
    hooks = data.setdefault("hooks", {})

    added = 0
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        # Drop any previous PhoneDeck entry so re-running is idempotent.
        for group in groups:
            group["hooks"] = [h for h in group.get("hooks", []) if not is_ours(h)]
        groups[:] = [g for g in groups if g.get("hooks")]
        groups.append({"hooks": [hook_entry()]})
        added += 1

    save(data)
    print(f"installed PhoneDeck hooks for {added} events in {SETTINGS}")
    print("Claude Code picks these up for newly started sessions.")


def remove() -> None:
    data = load()
    hooks = data.get("hooks") or {}

    removed = 0
    for event in list(hooks):
        groups = hooks.get(event) or []
        for group in groups:
            before = len(group.get("hooks", []))
            group["hooks"] = [h for h in group.get("hooks", []) if not is_ours(h)]
            removed += before - len(group["hooks"])
        hooks[event] = [g for g in groups if g.get("hooks")]
        if not hooks[event]:
            del hooks[event]

    if not hooks:
        data.pop("hooks", None)

    save(data)
    print(f"removed {removed} PhoneDeck hook(s) from {SETTINGS}")


def status() -> None:
    hooks = (load().get("hooks") or {})
    found = {event: sum(1 for g in groups for h in g.get("hooks", []) if is_ours(h))
             for event, groups in hooks.items()}
    found = {k: v for k, v in found.items() if v}
    if found:
        print("PhoneDeck hooks installed for:")
        for event in sorted(found):
            print(f"   {event}")
    else:
        print("no PhoneDeck hooks installed")
    other = sum(len(g.get("hooks", [])) for groups in hooks.values() for g in groups)
    print(f"total hooks in {SETTINGS.name}: {other}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true")
    group.add_argument("--remove", action="store_true")
    group.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.install:
        install()
    elif args.remove:
        remove()
    else:
        status()


if __name__ == "__main__":
    main()
