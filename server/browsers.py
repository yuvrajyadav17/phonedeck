"""Working out which browser to open a website group with.

A "group" of sites is most useful when it lands in its own window, separate
from whatever else is open. Doing that means launching the browser executable
directly with `--new-window` and every URL in the group, rather than handing
the URLs to the shell one at a time -- which just appends tabs to whichever
window happens to be in front.

Note on browser tab groups: Chromium's own named, coloured tab groups cannot be
created from outside the browser. There is no command-line switch for them and
no supported API; only an extension running inside the browser could. A
dedicated window is the closest equivalent that works.
"""
from __future__ import annotations

import logging
import os
import winreg
from pathlib import Path

log = logging.getLogger("phonedeck.browsers")

USER_CHOICE = (r"Software\Microsoft\Windows\Shell\Associations"
               r"\UrlAssociations\https\UserChoice")


def _executable_from_command(command: str) -> str | None:
    """Pull the program path out of a registry "shell open command" string.

    These look like:  "C:\\...\\comet.exe" --single-argument %1
    """
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        if end > 1:
            return command[1:end]
        return None
    # Unquoted: take everything up to the first space, which is only correct
    # for paths without spaces -- but unquoted entries are rare.
    return command.split(" ", 1)[0] or None


def default_browser() -> str | None:
    """Path to the user's default browser, or None if it cannot be determined."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_CHOICE) as key:
            progid = winreg.QueryValueEx(key, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            rf"{progid}\shell\open\command") as key:
            command = winreg.QueryValueEx(key, "")[0]
    except OSError:
        log.info("could not read the default browser from the registry")
        return None

    exe = _executable_from_command(str(command))
    if exe and Path(os.path.expandvars(exe)).exists():
        return os.path.expandvars(exe)
    return None


def build_command(urls: list[str], browser: str | None = None,
                  profile: str | None = None,
                  new_window: bool = True) -> list[str] | None:
    """Assemble a command line that opens a whole group at once.

    Returns None when no browser could be found, so the caller can fall back
    to handing the URLs to the shell individually.
    """
    exe = os.path.expandvars(browser) if browser else default_browser()
    if not exe or not Path(exe).exists():
        return None

    argv = [exe]
    if profile:
        # Chromium wants the directory name ("Profile 3"), not the display
        # name shown in the browser's profile menu.
        argv.append(f"--profile-directory={profile}")
    if new_window:
        argv.append("--new-window")
    argv.extend(urls)
    return argv
