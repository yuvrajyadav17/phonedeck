"""Synthetic keyboard input for Windows, via SendInput.

Deliberately dependency-free: this talks to user32 through ctypes rather than
pulling in pyautogui/keyboard, both of which drag in compiled wheels that lag
behind new Python releases (we are on 3.14).

Caveat worth knowing: Windows' UIPI will silently drop input aimed at a window
running at a higher integrity level than us. If a hotkey does nothing while an
admin app such as Task Manager is focused, that is why -- the fix is to run
PhoneDeck elevated too, not to change this code.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ------------------------------------------------------------ structures ----
ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001

# ------------------------------------------------------------- key table ----
MODIFIERS = {
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "menu": 0x12,
    "win": 0x5B,
    "super": 0x5B,
    "meta": 0x5B,
}

NAMED_KEYS = {
    "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09,
    "space": 0x20, "spacebar": 0x20,
    "backspace": 0x08, "back": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "prtsc": 0x2C,
    "capslock": 0x14,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "pause": 0x13,
    "apps": 0x5D, "menukey": 0x5D,
    # Media / volume -- these are what make the phone a usable remote.
    "media_play_pause": 0xB3, "playpause": 0xB3,
    "media_stop": 0xB2,
    "media_next": 0xB0, "next_track": 0xB0,
    "media_prev": 0xB1, "prev_track": 0xB1,
    "volume_mute": 0xAD, "mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "browser_back": 0xA6,
    "browser_forward": 0xA7,
    "browser_refresh": 0xA8,
    "browser_home": 0xAC,
}
for _i in range(1, 25):  # F1 - F24
    NAMED_KEYS[f"f{_i}"] = 0x6F + _i

# Keys that live on the extended half of the keyboard. Omitting the extended
# flag on these makes some applications read the numpad twin instead.
EXTENDED = {
    0x25, 0x26, 0x27, 0x28,  # arrows
    0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22,  # ins/del/home/end/pgup/pgdn
    0x2C, 0x90, 0x5B, 0x5D,  # printscreen, numlock, win, apps
    0xB0, 0xB1, 0xB2, 0xB3, 0xAD, 0xAE, 0xAF,  # media + volume
    0xA6, 0xA7, 0xA8, 0xAC,  # browser keys
}


class HotkeyError(ValueError):
    """Raised when a key combination cannot be parsed."""


def resolve_key(name: str) -> int:
    """Map a single key name to a Windows virtual-key code."""
    key = name.strip().lower()
    if not key:
        raise HotkeyError("empty key name")
    if key in MODIFIERS:
        return MODIFIERS[key]
    if key in NAMED_KEYS:
        return NAMED_KEYS[key]
    if len(key) == 1:
        if key.isalnum():
            return ord(key.upper())
        # Punctuation on a US layout. VkKeyScanW gives us the right code
        # together with any shift state, which _send_combo re-derives.
        res = user32.VkKeyScanW(ctypes.c_wchar(key))
        if res != -1:
            return res & 0xFF
    raise HotkeyError(f"unknown key: {name!r}")


def _make_key_input(vk: int, keyup: bool) -> INPUT:
    flags = KEYEVENTF_KEYUP if keyup else 0
    if vk in EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    return INPUT(
        type=INPUT_KEYBOARD,
        u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)),
    )


def _dispatch(inputs: list[INPUT]) -> None:
    if not inputs:
        return
    array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(f"SendInput sent {sent}/{len(inputs)} events "
                      f"(error {ctypes.get_last_error()})")


def send_combo(combo: str) -> None:
    """Press a combination such as ``ctrl+shift+esc`` once.

    Modifiers are held down for the duration of the final key and released in
    reverse order, which is what applications expect.
    """
    parts = [p for p in combo.replace(" ", "").split("+") if p]
    if not parts:
        raise HotkeyError(f"empty combination: {combo!r}")

    codes = [resolve_key(p) for p in parts]
    events: list[INPUT] = []
    for vk in codes:
        events.append(_make_key_input(vk, keyup=False))
    for vk in reversed(codes):
        events.append(_make_key_input(vk, keyup=True))
    _dispatch(events)


def send(combo: str, repeat: int = 1, gap: float = 0.02) -> None:
    """Send ``combo`` ``repeat`` times.

    Repeats matter for volume keys, where one press is a barely audible step.
    """
    repeat = max(1, min(int(repeat), 50))
    for i in range(repeat):
        if i:
            time.sleep(gap)
        send_combo(combo)


def move_mouse_relative(dx: int = 0, dy: int = 0) -> None:
    """Nudge the mouse by a relative amount.

    A zero-distance move still counts as user input, which is exactly what is
    needed to switch a sleeping display back on without disturbing anything on
    screen. All SendInput plumbing lives in this module, hence its home here.
    """
    event = INPUT(
        type=INPUT_MOUSE,
        u=_INPUTUNION(mi=MOUSEINPUT(dx=dx, dy=dy, mouseData=0,
                                    dwFlags=MOUSEEVENTF_MOVE, time=0,
                                    dwExtraInfo=0)),
    )
    _dispatch([event])


def type_text(text: str) -> None:
    """Type a literal string, layout-independently.

    Uses KEYEVENTF_UNICODE so the characters arrive exactly as written no
    matter what keyboard layout is active -- important for snippets containing
    symbols that move around between layouts.
    """
    events: list[INPUT] = []
    for ch in text:
        for keyup in (False, True):
            flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if keyup else 0)
            events.append(
                INPUT(
                    type=INPUT_KEYBOARD,
                    u=_INPUTUNION(
                        ki=KEYBDINPUT(wVk=0, wScan=ord(ch), dwFlags=flags,
                                      time=0, dwExtraInfo=0)
                    ),
                )
            )
        # SendInput takes a fixed-size array; chunk so very long snippets do
        # not build one enormous allocation.
        if len(events) >= 200:
            _dispatch(events)
            events = []
    _dispatch(events)
