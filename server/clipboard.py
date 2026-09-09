"""Reading and writing the Windows clipboard, via ctypes.

Used to paste dictated text rather than typing it. Synthetic keystrokes are
fine for a shortcut like Ctrl+C, but they are the wrong tool for a sentence:
injecting seventy characters as key events overruns the receiving
application's input queue, and the tail arrives as one repeated character with
no error reported anywhere. A paste is exact and takes the same time whatever
the length.

Whatever was on the clipboard is put back afterwards, so dictating does not
quietly cost you what you had copied.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

# The clipboard is a shared, single-owner resource: another application may
# hold it for a moment, so opening is retried briefly rather than failing.
OPEN_ATTEMPTS = 12
OPEN_DELAY = 0.02


def _open() -> bool:
    for _ in range(OPEN_ATTEMPTS):
        if user32.OpenClipboard(None):
            return True
        time.sleep(OPEN_DELAY)
    return False


def get_text() -> str | None:
    """Current clipboard text, or None if it holds something else."""
    if not _open():
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.c_wchar_p(pointer).value
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_text(text: str) -> bool:
    """Put text on the clipboard."""
    if not _open():
        return False
    try:
        user32.EmptyClipboard()
        buffer = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buffer)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return False
        ctypes.memmove(pointer, ctypes.byref(buffer), size)
        kernel32.GlobalUnlock(handle)
        # Ownership passes to the clipboard; the block must not be freed here.
        return bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        user32.CloseClipboard()
