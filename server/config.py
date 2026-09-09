"""Central configuration and paths for PhoneDeck.

Everything the rest of the app needs to know about *where things live* and
*how to authenticate* is resolved here, once, at import time.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

# ---------------------------------------------------------------- paths ----
ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
SHORTCUTS_FILE = ROOT / "shortcuts.json"
STATE_DIR = ROOT / ".state"
TOKEN_FILE = STATE_DIR / "token.txt"
LOG_FILE = STATE_DIR / "phonedeck.log"

# --------------------------------------------------------------- server ----
# Bound to loopback only: the phone reaches us through `adb reverse`, which
# tunnels the device's own localhost to ours over the USB cable. Nothing on
# the LAN can touch this port, which is the point.
HOST = "127.0.0.1"
PORT = 8770

# How often the dashboard polls /api/stats, in milliseconds.
STATS_POLL_MS = 1000

# Where to report weather for. Set explicitly, because IP geolocation put this
# machine ~160 km away (it reports wherever the ISP breaks out, not where you
# are). Open-Meteo answers for any coordinate by interpolating its grid, so the
# nearest available data is used automatically -- for these coordinates that is
# a point about 2 km away.
#
# Leave both as None to fall back to the IP lookup, cached in
# .state/location.json. WEATHER_PLACE is only the label shown on the panel;
# leave it None and the name is reverse-geocoded once and cached.
WEATHER_LAT: float | None = 27.9965829
WEATHER_LON: float | None = 76.1951099
WEATHER_PLACE: str | None = None


# ---------------------------------------------------------------- device ----
ADB = "adb"  # resolved via PATH; C:\platform-tools is already there

# Which phone to drive when more than one is plugged in. Empty means "the
# first one adb happens to list", which is a coin toss with two devices
# attached; set it to a serial from `adb devices` to pin it.
ANDROID_SERIAL = ""
ANDROID_PACKAGE = "com.phonedeck.shell"
ANDROID_ACTIVITY = f"{ANDROID_PACKAGE}/.MainActivity"


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def get_token() -> str:
    """Return the shared secret, generating it on first run.

    The token is what stops any *other* local process from driving your
    keyboard through this server. It is written once and reused forever so
    the phone does not need re-pairing after a restart.
    """
    _ensure_state_dir()
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


DEFAULT_SHORTCUTS = {
    "version": 1,
    # Three logo-only quick launchers in the top bar. Edited like any other
    # shortcut; a slot with no action renders as an empty placeholder.
    "topbar": [
        {
            "id": "slot1",
            "label": "Claude",
            # Store apps ship a far better logo than anything extractable from
            # the executable. "appx:" resolves the install folder by package
            # name, which survives updates -- the folder itself is version
            # stamped and cannot be listed without elevation.
            "icon_source": "appx:Claude|Assets\\Square150x150Logo.scale-200.png",
            "action": {"type": "aumid", "target": "Claude_pzs8sxrjxfjjc!Claude"},
        },
        {
            "id": "slot2",
            "label": "Comet \u2014 Yuvraj(Turing)",
            # Chromium keeps profiles in numbered directories; "Profile 3" is
            # the one named Yuvraj(Turing) in Comet's Local State.
            "action": {
                "type": "app",
                "target": "%LOCALAPPDATA%\\Perplexity\\Comet\\Application\\comet.exe",
                "args": ["--profile-directory=Profile 3"],
            },
        },
        {
            "id": "slot3",
            "label": "Slack",
            # "unplated" is the logo without its background tile, which sits
            # better on the dark chip than the plated variant.
            "icon_source": "appx:91750D7E.Slack|Assets\\SlackAppList.targetsize-512_altform-unplated.png",
            "action": {"type": "aumid", "target": "91750D7E.Slack_8she8kybcnzg4!Slack"},
        },
        {
            "id": "slot4",
            "label": "WhatsApp",
            "icon_source": "appx:5319275A.WhatsAppDesktop|Assets\\AppList.targetsize-256_altform-unplated.png",
            "action": {"type": "aumid",
                       "target": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"},
        },
    ],
    "groups": [
        {
            "id": "apps",
            "name": "Apps",
            "icon": "\U0001f5a5",
            "buttons": [
                {
                    "id": "notepad",
                    "label": "Notepad",
                    "icon": "\U0001f4dd",
                    "color": "#4c8dff",
                    "action": {"type": "app", "target": "notepad.exe"},
                },
                {
                    "id": "calc",
                    "label": "Calculator",
                    "icon": "\U0001f9ee",
                    "color": "#4c8dff",
                    "action": {"type": "app", "target": "calc.exe"},
                },
                {
                    "id": "explorer",
                    "label": "Downloads",
                    "icon": "\U0001f4c1",
                    "color": "#f0a94c",
                    "action": {"type": "app", "target": "%USERPROFILE%\\Downloads"},
                },
            ],
        },
        {
            "id": "edit",
            "name": "Edit",
            "icon": "\u2702",
            "buttons": [
                {
                    "id": "copy",
                    "label": "Copy",
                    "icon": "\U0001f4cb",
                    "color": "#38b48b",
                    "action": {"type": "hotkey", "keys": "ctrl+c"},
                },
                {
                    "id": "paste",
                    "label": "Paste",
                    "icon": "\U0001f4cc",
                    "color": "#38b48b",
                    "action": {"type": "hotkey", "keys": "ctrl+v"},
                },
                {
                    "id": "cut",
                    "label": "Cut",
                    "icon": "\u2702",
                    "color": "#38b48b",
                    "action": {"type": "hotkey", "keys": "ctrl+x"},
                },
                {
                    "id": "undo",
                    "label": "Undo",
                    "icon": "\u21a9",
                    "color": "#38b48b",
                    "action": {"type": "hotkey", "keys": "ctrl+z"},
                },
                {
                    "id": "selectall",
                    "label": "Select All",
                    "icon": "\u2b1a",
                    "color": "#38b48b",
                    "action": {"type": "hotkey", "keys": "ctrl+a"},
                },
                {
                    "id": "save",
                    "label": "Save",
                    "icon": "\U0001f4be",
                    "color": "#38b48b",
                    "action": {"type": "hotkey", "keys": "ctrl+s"},
                },
            ],
        },
        {
            "id": "media",
            "name": "Media",
            "icon": "\U0001f3b5",
            "buttons": [
                {
                    "id": "playpause",
                    "label": "Play / Pause",
                    "icon": "\u23ef",
                    "color": "#b57bee",
                    "action": {"type": "hotkey", "keys": "media_play_pause"},
                },
                {
                    "id": "next",
                    "label": "Next",
                    "icon": "\u23ed",
                    "color": "#b57bee",
                    "action": {"type": "hotkey", "keys": "media_next"},
                },
                {
                    "id": "prev",
                    "label": "Previous",
                    "icon": "\u23ee",
                    "color": "#b57bee",
                    "action": {"type": "hotkey", "keys": "media_prev"},
                },
                {
                    "id": "volup",
                    "label": "Vol +",
                    "icon": "\U0001f50a",
                    "color": "#b57bee",
                    "action": {"type": "hotkey", "keys": "volume_up", "repeat": 4},
                },
                {
                    "id": "voldown",
                    "label": "Vol -",
                    "icon": "\U0001f509",
                    "color": "#b57bee",
                    "action": {"type": "hotkey", "keys": "volume_down", "repeat": 4},
                },
                {
                    "id": "mute",
                    "label": "Mute",
                    "icon": "\U0001f507",
                    "color": "#b57bee",
                    "action": {"type": "hotkey", "keys": "volume_mute"},
                },
            ],
        },
        {
            "id": "web",
            "name": "Web",
            "icon": "\U0001f310",
            "buttons": [
                {
                    "id": "morning",
                    "label": "Morning Tabs",
                    "icon": "\u2615",
                    "color": "#e2617a",
                    "action": {
                        "type": "urls",
                        "targets": [
                            "https://mail.google.com",
                            "https://calendar.google.com",
                            "https://news.ycombinator.com",
                        ],
                    },
                },
                {
                    "id": "github",
                    "label": "GitHub",
                    "icon": "\U0001f419",
                    "color": "#e2617a",
                    "action": {"type": "urls", "targets": ["https://github.com"]},
                },
            ],
        },
        {
            "id": "system",
            "name": "System",
            "icon": "\u2699",
            "buttons": [
                {
                    "id": "lock",
                    "label": "Lock PC",
                    "icon": "\U0001f512",
                    "color": "#7b8794",
                    "action": {"type": "command", "target": "rundll32 user32.dll,LockWorkStation"},
                },
                {
                    # Windows offers no way to *unlock* a session -- the logon
                    # UI runs on a secure desktop no ordinary process can
                    # reach. Keeping the machine awake is the usable answer.
                    "id": "keepawake",
                    "label": "Keep Awake",
                    "icon": "☕",
                    "color": "#7b8794",
                    "action": {"type": "awake", "state": "toggle"},
                },
                {
                    "id": "wakescreen",
                    "label": "Wake Screen",
                    "icon": "\U0001f4a1",
                    "color": "#7b8794",
                    "action": {"type": "wake_display"},
                },
                {
                    "id": "showdesktop",
                    "label": "Show Desktop",
                    "icon": "\U0001f5a5",
                    "color": "#7b8794",
                    "action": {"type": "hotkey", "keys": "win+d"},
                },
                {
                    "id": "closeall",
                    "label": "Close All",
                    "icon": "✖",
                    "color": "#e2617a",
                    "confirm": "Close all open applications?",
                    # WM_CLOSE, not a kill: anything unsaved still prompts.
                    "action": {"type": "close_all"},
                },
                {
                    "id": "restart",
                    "label": "Restart",
                    "icon": "\U0001f501",
                    "color": "#e2617a",
                    "confirm": "Restart this PC?",
                    "action": {"type": "power", "mode": "restart", "delay": 15},
                },
                {
                    "id": "shutdown",
                    "label": "Shut Down",
                    "icon": "⏻",
                    "color": "#e2617a",
                    "confirm": "Shut down this PC?",
                    "action": {"type": "power", "mode": "shutdown", "delay": 15},
                },
                {
                    # The 15 second delay above exists so this is usable.
                    "id": "cancelshutdown",
                    "label": "Cancel Shutdown",
                    "icon": "⛔",
                    "color": "#38b48b",
                    "action": {"type": "power", "mode": "abort"},
                },
                {
                    "id": "emptytemp",
                    "label": "Clear Temp",
                    "icon": "\U0001f9f9",
                    "color": "#7b8794",
                    "action": {
                        "type": "chain",
                        "steps": [
                            {"type": "powershell", "target": "Get-ChildItem $env:TEMP -Recurse -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"},
                            {"type": "delay", "ms": 300},
                            {"type": "notify", "target": "Temp folder cleared"},
                        ],
                    },
                },
            ],
        },
    ],
}


def load_shortcuts() -> dict:
    """Read shortcuts.json, seeding it with defaults on first run."""
    if not SHORTCUTS_FILE.exists():
        save_shortcuts(DEFAULT_SHORTCUTS)
        return json.loads(json.dumps(DEFAULT_SHORTCUTS))
    with SHORTCUTS_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_shortcuts(data: dict) -> None:
    """Write shortcuts.json atomically so a crash mid-save cannot corrupt it."""
    SHORTCUTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SHORTCUTS_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    tmp.replace(SHORTCUTS_FILE)
