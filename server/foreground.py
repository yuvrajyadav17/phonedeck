"""Bring launched applications to the front.

Windows deliberately stops background processes from stealing focus. PhoneDeck
runs as a windowless pythonw process that never has the foreground and never
receives input, so an app it launches opens *behind* whatever you were looking
at -- which is wrong here, because the launch was a deliberate tap on a button.

``AllowSetForegroundWindow`` is the documented way to hand the privilege over,
but it only works for a process that is itself the foreground one (or was, or
received the last input event). None of that is true for this server, so it
fails. What does work is attaching to the current foreground thread's input
queue, which makes ``SetForegroundWindow`` legal for the duration.

The window to raise is found by watching which top-level windows appear after
the launch. That covers both a cold start and restoring an app from the
taskbar. When an app was already open and merely behind, no new window
appears; then a process-name hint is used instead.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes

import psutil

log = logging.getLogger("phonedeck.foreground")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SW_RESTORE = 9
POLL_SECONDS = 0.15

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.IsWindowVisible.restype = wintypes.BOOL


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def visible_windows() -> dict[int, int]:
    """Every visible top-level window with a title, as {hwnd: pid}."""
    found: dict[int, int] = {}

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            found[hwnd] = _window_pid(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return found


def force_foreground(hwnd: int) -> bool:
    """Raise a window past the foreground lock.

    Attaching our thread to the foreground window's input queue makes Windows
    treat the SetForegroundWindow call as coming from the active application,
    which is the only reliable way to do this from a background process.
    """
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)

        foreground = user32.GetForegroundWindow()
        if foreground == hwnd:
            return True

        target_thread = kernel32.GetCurrentThreadId()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None)

        attached = False
        if foreground_thread and foreground_thread != target_thread:
            attached = bool(user32.AttachThreadInput(target_thread,
                                                     foreground_thread, True))
        try:
            user32.BringWindowToTop(hwnd)
            ok = bool(user32.SetForegroundWindow(hwnd))
        finally:
            if attached:
                user32.AttachThreadInput(target_thread, foreground_thread, False)
        return ok
    except OSError:
        log.exception("could not raise window %s", hwnd)
        return False


def _normalise(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _matches_hint(pid: int, hint: str) -> bool:
    """Does this window's process plausibly belong to what we just launched?

    Compared on a shared prefix rather than a substring, because the two names
    frequently differ at the tail: the package "WhatsAppDesktop" runs as
    "WhatsApp.Root.exe", and neither string contains the other.
    """
    try:
        name = _normalise(psutil.Process(pid).name().removesuffix(".exe"))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

    target = _normalise(hint)
    if not name or not target:
        return False

    shared = 0
    for a, b in zip(name, target):
        if a != b:
            break
        shared += 1
    return shared >= 4 and shared >= min(len(name), len(target)) // 2


def _find_and_raise(before: dict[int, int], hint: str | None,
                    timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        current = visible_windows()

        # A window that was not there before: a fresh launch, or an app
        # restored from the taskbar.
        for hwnd in [h for h in current if h not in before]:
            title = _window_title(hwnd)
            if title:
                ok = force_foreground(hwnd)
                log.info("raised new window %r -> %s", title, ok)
                return

        # Already open and merely behind: fall back to the process name.
        if hint:
            for hwnd, pid in current.items():
                if _matches_hint(pid, hint) and _window_title(hwnd):
                    ok = force_foreground(hwnd)
                    log.info("raised existing window %r (hint %r) -> %s",
                             _window_title(hwnd), hint, ok)
                    return

    log.info("no window to raise (hint %r) within %.1fs", hint, timeout)


def raise_when_ready(before: dict[int, int], hint: str | None = None,
                     timeout: float = 6.0) -> None:
    """Watch for the launched app's window and bring it forward.

    Runs on its own thread: an application can take seconds to draw its first
    window, and the button tap should not wait for it.
    """
    thread = threading.Thread(
        target=_find_and_raise,
        args=(before, (hint or "").lower() or None, timeout),
        name="foreground",
        daemon=True,
    )
    thread.start()
