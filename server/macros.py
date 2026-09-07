"""Record and replay keyboard and mouse macros.

Recording uses Windows' low-level input hooks (WH_KEYBOARD_LL / WH_MOUSE_LL),
which observe input system-wide. They must run on a thread with a message
loop, so the recorder owns one.

Two deliberate choices about what is captured:

* **Injected input is ignored.** Windows flags events it synthesised, so
  PhoneDeck's own playback -- and its hotkey buttons -- cannot be recorded back
  into a macro and cause a feedback loop.
* **Idle mouse movement is skipped.** Only clicks and movement *while a button
  is held* are kept. A macro cares where you clicked and how you dragged, not
  the wander in between, and recording every move would bloat the file for
  nothing.

Replay is inherently position-based: it clicks where you clicked. If a window
has moved since, the macro clicks the wrong place. That is a property of
recorded macros generally, not something this can solve.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from typing import Any

from . import hotkeys

log = logging.getLogger("phonedeck.macros")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEWHEEL = 0x020A
WM_QUIT = 0x0012

LLKHF_INJECTED = 0x00000010
LLMHF_INJECTED = 0x00000001

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_WHEEL = 0x0800
BUTTON_FLAGS = {
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
}

# Guard rails: a runaway recording should not eat memory, and a replay should
# not be able to hold the machine hostage.
MAX_EVENTS = 5000
MAX_STEP_DELAY_MS = 5000
DRAG_SAMPLE_MS = 30


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


# LRESULT and handles are pointer-sized. Without explicit signatures ctypes
# assumes 32-bit ints, which truncates the module handle (SetWindowsHookEx then
# fails with "module not found") and overflows on the lparam pointer.
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int,
                              wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC,
                                     wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               ctypes.c_uint, ctypes.c_uint]
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, ctypes.c_uint,
                                      wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class Recorder:
    """Captures input until stopped, then hands back a replayable list."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._recording = False
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._last_time = 0.0
        self._buttons_down = 0
        self._last_move_at = 0.0
        self._started_at = 0.0
        self._hooks: list[Any] = []
        self._procs: list[Any] = []   # keep callbacks alive

    # ------------------------------------------------------------ state ----
    @property
    def recording(self) -> bool:
        with self._lock:
            return self._recording

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "recording": self._recording,
                "events": len(self._events),
                "seconds": round(time.time() - self._started_at, 1)
                if self._recording else 0,
            }

    # ------------------------------------------------------------ timing ----
    def _delay(self) -> int:
        now = time.time()
        if self._last_time == 0.0:
            self._last_time = now
            return 0
        gap = int((now - self._last_time) * 1000)
        self._last_time = now
        return max(0, min(gap, MAX_STEP_DELAY_MS))

    def _add(self, event: dict[str, Any]) -> None:
        with self._lock:
            if len(self._events) >= MAX_EVENTS:
                return
            self._events.append(event)

    # ------------------------------------------------------------- hooks ----
    def _on_key(self, code, wparam, lparam):
        if code >= 0:
            data = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not (data.flags & LLKHF_INJECTED):
                if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self._add({"k": data.vkCode, "d": 1, "t": self._delay()})
                elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                    self._add({"k": data.vkCode, "d": 0, "t": self._delay()})
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _on_mouse(self, code, wparam, lparam):
        if code >= 0:
            data = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (data.flags & LLMHF_INJECTED):
                x, y = data.pt.x, data.pt.y
                downs = {WM_LBUTTONDOWN: "left", WM_RBUTTONDOWN: "right",
                         WM_MBUTTONDOWN: "middle"}
                ups = {WM_LBUTTONUP: "left", WM_RBUTTONUP: "right",
                       WM_MBUTTONUP: "middle"}

                if wparam in downs:
                    self._buttons_down += 1
                    self._add({"b": downs[wparam], "d": 1, "x": x, "y": y,
                               "t": self._delay()})
                elif wparam in ups:
                    self._buttons_down = max(0, self._buttons_down - 1)
                    self._add({"b": ups[wparam], "d": 0, "x": x, "y": y,
                               "t": self._delay()})
                elif wparam == WM_MOUSEWHEEL:
                    turn = ctypes.c_short(data.mouseData >> 16).value
                    self._add({"w": turn, "x": x, "y": y, "t": self._delay()})
                elif wparam == WM_MOUSEMOVE and self._buttons_down:
                    # Only while dragging, and sampled, so a drag stays smooth
                    # without recording thousands of points.
                    now = time.time()
                    if (now - self._last_move_at) * 1000 >= DRAG_SAMPLE_MS:
                        self._last_move_at = now
                        self._add({"m": 1, "x": x, "y": y, "t": self._delay()})
        return user32.CallNextHookEx(None, code, wparam, lparam)

    # ------------------------------------------------------------- loop ----
    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        key_proc = HOOKPROC(self._on_key)
        mouse_proc = HOOKPROC(self._on_mouse)
        self._procs = [key_proc, mouse_proc]

        module = kernel32.GetModuleHandleW(None)
        kb = user32.SetWindowsHookExW(WH_KEYBOARD_LL, key_proc, module, 0)
        ms = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, module, 0)
        self._hooks = [h for h in (kb, ms) if h]

        if not self._hooks:
            log.error("could not install input hooks (error %s)",
                      ctypes.get_last_error())
            with self._lock:
                self._recording = False
            return

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        for handle in self._hooks:
            user32.UnhookWindowsHookEx(handle)
        self._hooks = []
        self._procs = []

    # --------------------------------------------------------------- api ----
    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._recording:
                return {"ok": False, "error": "already recording"}
            self._events = []
            self._recording = True
            self._started_at = time.time()
        self._last_time = 0.0
        self._buttons_down = 0
        self._last_move_at = 0.0

        self._thread = threading.Thread(target=self._run, name="macro-record",
                                        daemon=True)
        self._thread.start()
        time.sleep(0.15)  # let the hooks install before we report success
        if not self.recording:
            return {"ok": False, "error": "input hooks could not be installed"}
        return {"ok": True, "message": "recording"}

    def stop(self, trim_last_click: bool = False) -> dict[str, Any]:
        """Stop recording and return the events.

        ``trim_last_click`` drops the final click, which is only wanted when
        recording was stopped by clicking a button on the PC. Stopping from the
        phone touches nothing on the PC, so the last click is genuinely part of
        the macro and must be kept.
        """
        with self._lock:
            if not self._recording:
                return {"ok": False, "error": "not recording"}
            self._recording = False
            events = list(self._events)

        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None

        if trim_last_click:
            events = _drop_final_click(events)
        return {"ok": True, "events": events, "count": len(events),
                "message": f"recorded {len(events)} event(s)"}


def _drop_final_click(events: list[dict]) -> list[dict]:
    """Remove the trailing button press/release pair, if the last event is one."""
    if not (events and events[-1].get("b") and events[-1].get("d") == 0):
        return events
    button = events[-1]["b"]
    events = events[:-1]
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("b") == button and events[i].get("d") == 1:
            del events[i]
            break
    return events


# ------------------------------------------------------------- playback ----
def _to_absolute(x: int, y: int) -> tuple[int, int]:
    """Screen pixels to the 0-65535 space SendInput expects."""
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or 1
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or 1
    nx = int((x - left) * 65535 / max(1, width - 1))
    ny = int((y - top) * 65535 / max(1, height - 1))
    return max(0, min(65535, nx)), max(0, min(65535, ny))


def _mouse_input(flags: int, x: int | None = None, y: int | None = None,
                 data: int = 0) -> hotkeys.INPUT:
    dx = dy = 0
    if x is not None and y is not None:
        dx, dy = _to_absolute(x, y)
        flags |= MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    return hotkeys.INPUT(
        type=hotkeys.INPUT_MOUSE,
        u=hotkeys._INPUTUNION(mi=hotkeys.MOUSEINPUT(
            dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF, dwFlags=flags,
            time=0, dwExtraInfo=0)),
    )


def play(events: list[dict[str, Any]], speed: float = 1.0) -> str:
    """Replay a recorded macro."""
    if not isinstance(events, list) or not events:
        raise ValueError("macro has no events")
    if len(events) > MAX_EVENTS:
        raise ValueError(f"macro too long ({len(events)} events)")

    speed = max(0.1, min(float(speed or 1.0), 10.0))

    for event in events:
        delay = min(int(event.get("t", 0)), MAX_STEP_DELAY_MS) / 1000.0
        if delay:
            time.sleep(delay / speed)

        if "k" in event:
            vk = int(event["k"])
            hotkeys._dispatch([hotkeys._make_key_input(vk, keyup=not event.get("d"))])
        elif "b" in event:
            down, up = BUTTON_FLAGS.get(str(event["b"]), BUTTON_FLAGS["left"])
            hotkeys._dispatch([
                _mouse_input(MOUSEEVENTF_MOVE, event.get("x"), event.get("y")),
                _mouse_input(down if event.get("d") else up),
            ])
        elif "m" in event:
            hotkeys._dispatch([_mouse_input(MOUSEEVENTF_MOVE,
                                            event.get("x"), event.get("y"))])
        elif "w" in event:
            hotkeys._dispatch([_mouse_input(MOUSEEVENTF_WHEEL,
                                            event.get("x"), event.get("y"),
                                            int(event["w"]))])

    return f"played {len(events)} event(s)"


recorder = Recorder()
