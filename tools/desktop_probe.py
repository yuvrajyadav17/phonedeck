"""Show which Windows desktop is receiving input, once a second.

Run this, lock the PC, wait a few seconds, unlock, then read the log. It
records what a program running as you can see at each moment.

    python tools/desktop_probe.py

You will see something like:

    14:02:01  input desktop = Default        <- unlocked, we can send input here
    14:02:09  OpenInputDesktop FAILED (5)    <- locked: access denied
    14:02:18  input desktop = Default        <- unlocked again

That middle stretch is the whole answer to "why can't PhoneDeck type my PIN".
While the machine is locked, input belongs to the Winlogon desktop, and a
process running as you is refused even *read* access to it -- never mind
sending keystrokes. Error 5 is ERROR_ACCESS_DENIED.

This is the boundary that stops malware typing your PIN, so it is not
something to be worked around. Only a Credential Provider -- a system
component registered with Winlogon, installed as administrator, running as
SYSTEM -- lives on the other side.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

UOI_NAME = 2
DESKTOP_READOBJECTS = 0x0001

user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenInputDesktop.restype = wintypes.HANDLE
user32.GetUserObjectInformationW.argtypes = [
    wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]
user32.GetUserObjectInformationW.restype = wintypes.BOOL
user32.CloseDesktop.argtypes = [wintypes.HANDLE]


def input_desktop_name() -> str:
    """Name of the desktop currently receiving input, or why we cannot tell."""
    handle = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not handle:
        return f"OpenInputDesktop FAILED ({ctypes.get_last_error()})"
    try:
        buf = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        if not user32.GetUserObjectInformationW(handle, UOI_NAME, buf,
                                                ctypes.sizeof(buf),
                                                ctypes.byref(needed)):
            return f"name unreadable ({ctypes.get_last_error()})"
        return f"input desktop = {buf.value}"
    finally:
        user32.CloseDesktop(handle)


def main() -> None:
    print(__doc__.split("Run this")[0].strip())
    print("Watching. Lock the PC (Win+L), wait, then unlock. Ctrl+C to stop.\n")
    previous = None
    try:
        while True:
            line = input_desktop_name()
            stamp = time.strftime("%H:%M:%S")
            # Only print on change, plus a heartbeat, so the log stays readable.
            if line != previous:
                print(f"{stamp}  {line}")
                previous = line
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
