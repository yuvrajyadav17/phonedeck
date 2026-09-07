"""System-tray presence for the background server.

Without this the server is invisible: nothing to click, no way to tell whether
it is running, and no way to stop it short of Task Manager. The tray icon gives
it a face -- double-click opens the editor, and the menu covers the rest.

Kept entirely optional. If pystray or Pillow are missing the server still runs
exactly as before; see app.main().
"""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

import pystray
from PIL import Image

from . import power
from .config import HOST, PORT, ROOT, get_token

log = logging.getLogger("phonedeck.tray")

ICON_FILE = ROOT / "assets" / "phonedeck.png"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0)


def _open_editor() -> None:
    """Launch the standalone editor window as its own process.

    A separate process rather than a window in this one: pywebview must own the
    main thread, which the tray already holds, and it does not reliably restart
    after its window is closed.
    """
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else sys.executable)
    try:
        subprocess.Popen([exe, "editor_app.py"], cwd=str(ROOT),
                         creationflags=NO_WINDOW | DETACHED, close_fds=True)
    except OSError:
        log.exception("could not start the editor window")


def _open_dashboard() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}/?t={get_token()}")


def run(bridge) -> None:
    """Show the tray icon and block until the user quits."""
    image = Image.open(ICON_FILE)

    def relaunch_on_phone(_icon=None, _item=None) -> None:
        result = bridge.relaunch()
        log.info("relaunch: %s", result.get("message"))

    def device_status(_item=None) -> str:
        state = bridge.snapshot()
        if state["status"] == "ready":
            return "Phone: connected" + ("" if state["app_launched"]
                                         else " (app not started)")
        return f"Phone: {state['status']}"

    def quit_all(icon, _item=None) -> None:
        icon.stop()
        # The HTTP server and watchdog are daemon threads; leaving normally can
        # still hang on the WSGI accept loop, so end the process outright.
        os._exit(0)

    def toggle_awake(_icon=None, _item=None) -> None:
        power.keep_awake.toggle()

    def wake_display(_icon=None, _item=None) -> None:
        power.wake_display()

    def lock_pc(_icon=None, _item=None) -> None:
        ctypes.WinDLL("user32").LockWorkStation()

    menu = pystray.Menu(
        pystray.MenuItem("Open editor", lambda i, x: _open_editor(), default=True),
        pystray.MenuItem("Open dashboard in browser", lambda i, x: _open_dashboard()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(device_status, None, enabled=False),
        pystray.MenuItem("Wake phone and relaunch app", relaunch_on_phone),
        pystray.Menu.SEPARATOR,
        # There is no "unlock": Windows runs the logon UI on a secure desktop
        # that no ordinary process can reach, and offers no counterpart to
        # LockWorkStation. Keeping the machine awake is the practical answer.
        pystray.MenuItem("Keep PC awake", toggle_awake,
                         checked=lambda _item: power.keep_awake.enabled),
        pystray.MenuItem("Wake display", wake_display),
        pystray.MenuItem("Lock PC", lock_pc),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit PhoneDeck", quit_all),
    )

    icon = pystray.Icon("phonedeck", image, "PhoneDeck", menu)
    icon.run()
