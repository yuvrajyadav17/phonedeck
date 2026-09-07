"""The shortcut engine -- what actually happens when a button is tapped.

Every button in shortcuts.json carries an ``action`` object whose ``type``
selects one of the handlers below. A ``chain`` action nests a list of the same
step objects, which is what turns "a long piece of work" into one tap.

Note on trust: these actions run arbitrary programs and shell commands by
design. The only thing standing between the network and your machine is that
the server binds to loopback and demands a token -- see config.py.
"""
from __future__ import annotations

import os
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any

import psutil

from . import browsers, foreground, hotkeys, macros, power

# Windows: keep spawned console tools from flashing a black window on screen.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0)

# A chain that runs away would hold the request open forever.
MAX_STEPS = 50
MAX_CHAIN_SECONDS = 120
COMMAND_TIMEOUT = 60


class ActionError(RuntimeError):
    """Raised when an action is malformed or fails to start."""


def _expand(value: str) -> str:
    """Resolve %ENVIRONMENT% variables and ~ in a user-supplied path."""
    return os.path.expandvars(os.path.expanduser(value))


# ------------------------------------------------------------- handlers ----
def _wants_foreground(step: dict[str, Any]) -> bool:
    """Launches come to the front unless a step opts out with foreground:false."""
    return step.get("foreground", True) is not False


def _do_app(step: dict[str, Any]) -> str:
    """Launch a program, document or folder and return immediately."""
    target = step.get("target")
    if not target:
        raise ActionError("'app' action needs a 'target'")
    target = _expand(str(target))
    args = [str(a) for a in step.get("args", [])]
    cwd = _expand(str(step["cwd"])) if step.get("cwd") else None

    path = Path(target)

    # Snapshot before launching, so the new window can be told apart from the
    # ones already on screen.
    raise_it = _wants_foreground(step)
    before = foreground.visible_windows() if raise_it else {}
    hint = step.get("window_hint") or path.stem
    # Folders and documents have no argv, so hand them to the shell to open
    # with whatever the user has associated. Executables we start directly so
    # arguments and working directory behave predictably.
    if not args and (path.is_dir() or (path.exists() and path.suffix.lower() not in
                                       (".exe", ".bat", ".cmd", ".com"))):
        os.startfile(str(path))  # noqa: S606 - deliberate, this is the feature
        if raise_it:
            foreground.raise_when_ready(before, hint)
        return f"opened {target}"

    try:
        subprocess.Popen(
            [target, *args],
            cwd=cwd,
            close_fds=True,
            creationflags=_DETACHED | _NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise ActionError(f"not found: {target}") from exc
    if raise_it:
        foreground.raise_when_ready(before, hint)
    return f"launched {target}"


def _run_shell(command: str, shell: str) -> str:
    """Run a command and capture its output, so failures are visible."""
    if shell == "powershell":
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command", command]
    else:
        argv = ["cmd.exe", "/c", command]

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise ActionError(f"timed out after {COMMAND_TIMEOUT}s") from exc

    output = (proc.stdout or "").strip()
    error = (proc.stderr or "").strip()
    if proc.returncode != 0:
        detail = error or output or f"exit code {proc.returncode}"
        raise ActionError(detail[:400])
    return (output or "done")[:400]


def _do_aumid(step: dict[str, Any]) -> str:
    """Launch a Store/MSIX app by its AppUserModelID.

    Packaged apps live under a version-stamped WindowsApps folder that changes
    on every update, and launching that path directly is often blocked. The
    AppUserModelID is stable, and the shell knows how to start it.

    Uses ShellExecute (os.startfile) rather than spawning
    ``explorer.exe shell:appsFolder\\...``: the explorer form silently does
    nothing on this machine -- it returns success and no app appears --
    whereas ShellExecute launches correctly and raises on a bad id.
    """
    aumid = step.get("target") or step.get("aumid")
    if not aumid:
        raise ActionError("'aumid' action needs a 'target'")

    raise_it = _wants_foreground(step)
    before = foreground.visible_windows() if raise_it else {}
    # "91750D7E.Slack_8she8kybcnzg4!Slack" -> "Slack". The package name is a
    # far better guess at the process name than the application id after "!",
    # which is often just "App".
    package = str(aumid).split("_", 1)[0]
    hint = step.get("window_hint") or package.rsplit(".", 1)[-1]

    try:
        os.startfile(f"shell:appsFolder\\{aumid}")  # noqa: S606 - the feature
    except OSError as exc:
        raise ActionError(f"could not launch {aumid}: {exc}") from exc

    if raise_it:
        foreground.raise_when_ready(before, hint)
    return f"launched {aumid}"


def _do_command(step: dict[str, Any]) -> str:
    target = step.get("target")
    if not target:
        raise ActionError("'command' action needs a 'target'")
    return _run_shell(str(target), "cmd")


def _do_powershell(step: dict[str, Any]) -> str:
    target = step.get("target")
    if not target:
        raise ActionError("'powershell' action needs a 'target'")
    return _run_shell(str(target), "powershell")


def _do_urls(step: dict[str, Any]) -> str:
    """Open one or many URLs -- a whole working set of tabs in one tap."""
    targets = step.get("targets") or ([step["target"]] if step.get("target") else [])
    if not targets:
        raise ActionError("'urls' action needs 'targets'")

    urls = [str(u) for u in targets]
    raise_it = _wants_foreground(step)
    before = foreground.visible_windows() if raise_it else {}

    # A website group is far more useful in its own window than as tabs
    # appended to whatever was in front, so that is the default. Set
    # "new_window": false for the old behaviour.
    new_window = step.get("new_window", True) is not False
    argv = browsers.build_command(
        urls,
        browser=step.get("browser"),
        profile=step.get("profile"),
        new_window=new_window,
    )

    if argv is not None:
        try:
            subprocess.Popen(argv, close_fds=True,
                             creationflags=_DETACHED | _NO_WINDOW)
        except OSError as exc:
            raise ActionError(f"could not start the browser: {exc}") from exc
        opened_where = "a new window" if new_window else "the browser"
    else:
        # No browser path available: hand each URL to the shell instead.
        for i, url in enumerate(urls):
            if i:
                # Browsers drop tabs opened in a tight loop from a cold start.
                time.sleep(0.35)
            webbrowser.open(url)
        opened_where = "the default browser"

    if raise_it:
        foreground.raise_when_ready(before, step.get("window_hint"))
    return f"opened {len(urls)} site(s) in {opened_where}"


def _do_hotkey(step: dict[str, Any]) -> str:
    keys = step.get("keys") or step.get("target")
    if not keys:
        raise ActionError("'hotkey' action needs 'keys'")
    repeat = int(step.get("repeat", 1))
    hotkeys.send(str(keys), repeat=repeat)
    return f"sent {keys}" + (f" x{repeat}" if repeat > 1 else "")


def _do_text(step: dict[str, Any]) -> str:
    text = step.get("text") or step.get("target")
    if text is None:
        raise ActionError("'text' action needs 'text'")
    hotkeys.type_text(str(text))
    return f"typed {len(str(text))} chars"


def _do_delay(step: dict[str, Any]) -> str:
    ms = int(step.get("ms", step.get("target", 200)))
    ms = max(0, min(ms, 10_000))
    time.sleep(ms / 1000.0)
    return f"waited {ms}ms"


def _do_awake(step: dict[str, Any]) -> str:
    """Keep the PC from sleeping or blanking its display.

    ``state`` is "on", "off", or "toggle" (the default), so one button can act
    as a switch.
    """
    state = str(step.get("state") or step.get("target") or "toggle").lower()
    if state in ("on", "true", "1", "yes"):
        value = power.keep_awake.set(True)
    elif state in ("off", "false", "0", "no"):
        value = power.keep_awake.set(False)
    elif state == "toggle":
        value = power.keep_awake.toggle()
    else:
        raise ActionError(f"'awake' state must be on, off or toggle, not {state!r}")
    return "keeping PC awake" if value else "PC may sleep again"


def _do_wake_display(_step: dict[str, Any]) -> str:
    return power.wake_display()


def _do_system_power(step: dict[str, Any]) -> str:
    """Shut down, restart, sign out, or cancel a pending shutdown."""
    mode = str(step.get("mode") or step.get("target") or "").lower()
    if not mode:
        raise ActionError("'power' action needs a 'mode': shutdown, restart, "
                          "logoff or abort")
    try:
        return power.system_power(mode, int(step.get("delay", 0)))
    except (ValueError, OSError) as exc:
        raise ActionError(str(exc)) from exc


def _do_close_all(step: dict[str, Any]) -> str:
    """Ask open applications to close, leaving the desktop itself alone."""
    return power.close_all_windows(keep=step.get("keep"), only=step.get("only"))


def _do_macro(step: dict[str, Any]) -> str:
    """Replay a recorded keyboard/mouse macro."""
    events = step.get("events")
    try:
        return macros.play(events, speed=float(step.get("speed", 1.0)))
    except (ValueError, TypeError) as exc:
        raise ActionError(str(exc)) from exc


def _do_notify(step: dict[str, Any]) -> str:
    """A no-op on the PC that surfaces as a toast on the phone."""
    return str(step.get("target") or step.get("text") or "")


HANDLERS = {
    "app": _do_app,
    "aumid": _do_aumid,
    "store": _do_aumid,
    "command": _do_command,
    "cmd": _do_command,
    "powershell": _do_powershell,
    "ps": _do_powershell,
    "urls": _do_urls,
    "url": _do_urls,
    "hotkey": _do_hotkey,
    "keys": _do_hotkey,
    "text": _do_text,
    "type": _do_text,
    "delay": _do_delay,
    "wait": _do_delay,
    "notify": _do_notify,
    "awake": _do_awake,
    "keep_awake": _do_awake,
    "wake_display": _do_wake_display,
    "power": _do_system_power,
    "close_all": _do_close_all,
    "macro": _do_macro,
}


def run_step(step: dict[str, Any]) -> str:
    kind = str(step.get("type", "")).lower()
    handler = HANDLERS.get(kind)
    if handler is None:
        raise ActionError(f"unknown action type: {kind!r}")
    try:
        return handler(step)
    except ActionError:
        raise
    except Exception as exc:  # noqa: BLE001
        # Handlers raise their own domain errors -- HotkeyError for an unknown
        # key name, OSError from a failed launch. Funnel them all into
        # ActionError so callers get one predictable failure type, and the API
        # answers with a readable message instead of an HTML 500 page.
        raise ActionError(f"{kind}: {exc}") from exc


def run_action(action: dict[str, Any]) -> dict[str, Any]:
    """Execute one button's action, chained or single.

    Returns a per-step report rather than a bare success flag, so the phone can
    show exactly which step of a long chain broke.
    """
    if not isinstance(action, dict):
        raise ActionError("action must be an object")

    kind = str(action.get("type", "")).lower()
    if kind != "chain":
        message = run_step(action)
        return {"ok": True, "message": message, "steps": []}

    steps = action.get("steps") or []
    if not isinstance(steps, list):
        raise ActionError("'chain' action needs a 'steps' list")
    if len(steps) > MAX_STEPS:
        raise ActionError(f"chain too long ({len(steps)} steps, max {MAX_STEPS})")

    started = time.monotonic()
    report: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if time.monotonic() - started > MAX_CHAIN_SECONDS:
            report.append({"index": index, "ok": False,
                           "message": "chain aborted: exceeded time budget"})
            return {"ok": False, "message": "chain timed out", "steps": report}
        try:
            message = run_step(step)
            report.append({"index": index, "ok": True, "message": message})
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
            report.append({"index": index, "ok": False, "message": str(exc)})
            # Default is fail-fast; a step may opt out with "continue_on_error".
            if not step.get("continue_on_error"):
                return {"ok": False,
                        "message": f"step {index + 1} failed: {exc}",
                        "steps": report}

    succeeded = sum(1 for r in report if r["ok"])
    return {"ok": True, "message": f"{succeeded}/{len(report)} steps ok",
            "steps": report}


def find_button(shortcuts: dict[str, Any], button_id: str) -> dict[str, Any] | None:
    """Look up a button by id, in the drawer groups or the top-bar slots.

    Both are launched through the same endpoint, so the top bar needs no
    parallel machinery of its own.
    """
    for group in shortcuts.get("groups", []):
        for button in group.get("buttons", []):
            if button.get("id") == button_id:
                return button
    for slot in shortcuts.get("topbar", []):
        if slot.get("id") == button_id and slot.get("action"):
            return slot
    return None


def find_slot(shortcuts: dict[str, Any], slot_id: str) -> dict[str, Any] | None:
    for slot in shortcuts.get("topbar", []):
        if slot.get("id") == slot_id:
            return slot
    return None


def kill_process(pid: int) -> str:
    """End a task from the phone's process list."""
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
        return f"ended {name} ({pid})"
    except psutil.NoSuchProcess as exc:
        raise ActionError(f"no such process: {pid}") from exc
    except psutil.AccessDenied as exc:
        raise ActionError(
            f"access denied for pid {pid}; run PhoneDeck as administrator"
        ) from exc
