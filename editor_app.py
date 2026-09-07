"""PhoneDeck Editor -- a standalone desktop window for editing shortcuts.

Double-click this (or the Start Menu shortcut) and the editor opens as a real
application window: no address bar, no token to paste, no browser tab to find
among thirty others.

It is only a shell around the editor the server already serves, which is what
keeps the two from drifting apart -- there is exactly one editor, and this
window shows it.

If the background server is not running, this starts it first.
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import webview  # pywebview: a native window over the system WebView2

ROOT = Path(__file__).resolve().parent
ICON_FILE = ROOT / "assets" / "phonedeck.ico"
TOKEN_FILE = ROOT / ".state" / "token.txt"
HEALTH_URL = "http://127.0.0.1:8770/api/health"
EDITOR_URL = "http://127.0.0.1:8770/editor?t={token}"

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
START_TIMEOUT = 25.0


def server_is_up(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def start_server() -> bool:
    """Launch the background server and wait for it to answer."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else sys.executable)

    subprocess.Popen(
        [exe, "run.py"],
        cwd=str(ROOT),
        creationflags=NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0),
        close_fds=True,
    )

    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if server_is_up():
            return True
        time.sleep(0.5)
    return False


def read_token() -> str | None:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def fail(message: str) -> None:
    """Report a startup problem in a window, since there is no console here."""
    webview.create_window(
        "PhoneDeck Editor",
        html=(
            "<body style=\"margin:0;background:#0d1219;color:#e8eef7;"
            "font:14px/1.5 'Segoe UI',system-ui,sans-serif;display:flex;"
            "align-items:center;justify-content:center;height:100vh\">"
            f"<div style='max-width:34em;padding:2em'>{message}</div></body>"
        ),
        width=560, height=280,
    )
    webview.start()
    sys.exit(1)


class Api:
    """Bridge for things the page cannot do from inside a WebView.

    A ``target="_blank"`` link simply does nothing here -- there is no browser
    to open a tab in -- so the editor calls this instead when it detects that
    it is running inside the desktop shell.
    """

    def __init__(self, token: str) -> None:
        self._token = token

    def open_dashboard(self) -> bool:
        webbrowser.open(f"http://127.0.0.1:8770/?t={self._token}")
        return True


def main() -> None:
    if not server_is_up() and not start_server():
        fail("<h3>PhoneDeck is not running</h3>"
             "<p>The editor could not reach the server on port 8770, and "
             "starting it timed out.</p>"
             "<p>Try running <code>python run.py</code> from the project "
             "folder to see the error.</p>")

    token = read_token()
    if token is None:
        fail("<h3>No access token yet</h3>"
             "<p>Start PhoneDeck once so it can create "
             "<code>.state/token.txt</code>, then reopen the editor.</p>")

    webview.create_window(
        "PhoneDeck Editor",
        EDITOR_URL.format(token=token),
        width=1220,
        height=840,
        min_size=(900, 620),
        background_color="#0d1219",
        js_api=Api(token),
    )
    # Blocks until the window is closed; the background server keeps running.
    # Without an explicit icon the window inherits pythonw's generic one.
    webview.start(icon=str(ICON_FILE) if ICON_FILE.exists() else None)


if __name__ == "__main__":
    main()
