# PhoneDeck

Turns a spare Android phone, tethered by USB, into a permanent second panel for
a Windows PC: a live system readout plus an app-drawer of shortcuts that launch
programs, run command chains, open sets of websites, and send hotkeys.

Built for a Realme 1 (CPH1859) on Android 9, but nothing is specific to it
beyond the minimum SDK.

---

## How it fits together

```
   Windows PC                                    Phone
   ──────────                                    ─────
   run.py
     ├── server/app.py      HTTP on 127.0.0.1:8770 ◄── WebView loads
     │     ├── /api/stats        psutil                localhost:8770
     │     ├── /api/shortcuts    shortcuts.json        through the
     │     └── /api/run/<id>     actions.py            USB tunnel
     │
     └── server/bridge.py   ──── adb ────────────────► wake screen
           watchdog loop                               am start the app
                                                       adb reverse tunnel
```

The phone is passive. The PC does everything: it opens the tunnel, wakes the
screen and starts the app. That is why "it comes up on its own when the PC
boots" works, and why it recovers by itself when the cable is unplugged and
plugged back in.

**No network exposure.** The server binds to `127.0.0.1` only. The phone
reaches it through `adb reverse`, which tunnels the *device's* localhost to the
PC's over the USB cable. Nothing is listening on your LAN, and every `/api/`
call additionally requires a token stored in `.state/token.txt`.

---

## Running it

The server starts at login and lives in the **system tray**. Its menu opens the
editor, opens the dashboard in a browser, wakes the phone and relaunches the
app, and quits. Double-clicking the tray icon opens the editor.

To run it by hand instead:

```bash
python run.py
```

The dashboard is also reachable at `http://127.0.0.1:8770/?t=<token>` in any
browser; the token is printed at startup and stored in `.state/token.txt`.

Windows integration — Startup entry, Start Menu and desktop shortcuts — is
installed by:

```bash
powershell -ExecutionPolicy Bypass -File install_autostart.ps1
```

Add `-NoDesktop` to skip the desktop shortcut, or `-Remove` to take all of it
back off.

---

## The dashboard

Landscape — the phone lying on its side, which is how it is meant to sit — is
the three-column board:

| Column | Contents | Scrolling |
|---|---|---|
| Left | CPU, RAM and GPU cards, each accented in its own colour | Its own scroll |
| Centre | Network, and Disk I/O | Locked — never scrolls |
| Right | Top processes, with a CPU / RAM switch | Its own scroll |

The top bar carries the uptime clock, the CPU and GPU temperatures (each dot
matching its card's colour), the connection dot, and the menu that opens the
shortcut drawer.

**Swipe the Disk I/O card** left or right to page through the drives one at a
time; the dots underneath show where you are. **Hold a process** to end it.

Rotating the phone to portrait stacks the same three columns into one
scrolling page. That is done entirely by CSS media queries — no JavaScript
measures the window — so it rearranges the instant the phone turns. The app is
declared `fullUser`, meaning it obeys the system rotation lock: set the phone
to landscape once and it stays there even lying flat, where the sensor cannot
tell up from down.

Scrollbars are hidden throughout; the panes still scroll.

---

## Top-bar launchers

Four logo-only quick launchers sit next to the temperatures, showing each
application's real icon rather than a stand-in emoji. They are edited in the
**Top bar** list at the top of the editor, exactly like any other shortcut, and
an unassigned slot shows a dashed placeholder.

Currently: **Claude**, **Comet** (opening the *Yuvraj(Turing)* profile),
**Slack** and **WhatsApp**.

The count lives in `SLOT_COUNT`, declared in both `web/app.js` and
`web/editor.js` — change both together. The editor pads a shorter saved config
up to that number rather than replacing it, so raising the count keeps existing
slots and simply adds empty ones.

**Icons** come from `/api/icon/<slot>`, which resolves per slot:

* an explicit `icon_source` path, if set
* otherwise the executable the action launches, with the icon extracted at the
  largest size Windows offers (256px typically) and cached under `.state/icons/`

For Store apps set `icon_source` to `appx:<PackageName>|<relative asset>` —
for example `appx:Claude|Assets\Square150x150Logo.scale-200.png`. The package
folder is version stamped and changes on every update, and it cannot be
*listed* without elevation (a wildcard there always comes back empty), so the
install location is resolved by package name instead. The shipped Store logo is
also far crisper than anything extractable from the .exe.

Only slot ids that appear in `shortcuts.json` resolve, so the icon endpoint
cannot be used to read arbitrary files off the machine.

**Chromium profiles.** Comet, like any Chromium browser, selects a profile with
`--profile-directory`, and the directory name is not the display name — the
mapping lives in `…\Comet\User Data\Local State`. Here `Profile 3` is the one
named *Yuvraj(Turing)*. The editor's argument field is quote-aware precisely
because that value contains a space.

**Store apps are launched with ShellExecute**, not by spawning
`explorer.exe shell:appsFolder\…`. The explorer form reports success and then
silently does nothing on this machine; `os.startfile` launches correctly and
raises on an unknown id, so a mistyped AppUserModelID is reported rather than
swallowed.

---

## The Claude tracker

A status light in the top bar: grey off, green idle, blue working, amber
asking, red error, purple limit.

Which sessions exist comes from Claude's own `~/.claude/sessions` registry, so
the light is right the moment Claude opens and after PhoneDeck restarts. What
each session is *doing* comes from Claude Code **hooks** posting to
`/api/claude/hook` -- install with `python tools/claude_hooks.py --install`,
remove with `--remove`; the settings file is backed up first. Only
low-frequency events are hooked, so no latency is added to individual tool
calls.

That endpoint is deliberately unauthenticated and always returns 200: Claude
reads a 4xx from a hook as an instruction to block the action, so rejecting a
request could stall a real session for the sake of a status light. Sessions
that die without firing `SessionEnd` are pruned by cross-checking Claude's own
`~/.claude/sessions` registry.

There is deliberately **no usage readout**. The session and weekly percentages
`/usage` reports come from the API, are stored nowhere on disk, and have no CLI
equivalent (`claude` has no `usage` subcommand), so nothing outside Claude can
read them. Raw token counts were measurable, but a number that is not the limit
is not worth the space, so the card was removed rather than kept as a
near-miss.

---

## Temperatures

These are the one thing Windows will not tell a program without help.

**GPU works out of the box** via `nvidia-smi`, which ships with the NVIDIA
driver — temperature, load, VRAM and power all come from it.

**CPU package temperature needs [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)**,
because nothing built into Windows exposes it. Until it is running the top bar
shows `--` rather than inventing a number. To switch it on:

1. Download LibreHardwareMonitor and run it **as administrator** (it needs that
   to read the sensors at all).
2. Either leave it running — the WMI provider is picked up automatically — or
   turn on *Options → Remote Web Server → Run* for a faster, lighter path.

`server/sensors.py` probes the web server first, falls back to WMI, and gives
up quietly for a minute before retrying, so a missing provider costs nothing.
All of it is sampled on a background thread: `nvidia-smi` takes a few hundred
milliseconds per call, far too slow to sit in a once-a-second poll.

---

## Editing shortcuts

Open **PhoneDeck Editor** — from the desktop, the Start Menu, or the tray icon.
It is a real application window, so there is no browser tab to find and no
token to paste. If the server is not running it starts it first, which means
the shortcut works from a cold machine.

Add groups and buttons, hit **Test now** to fire one without leaving the
window, then **Save** (or Ctrl+S). Changes reach the phone the next time the
drawer is opened.

The window is a shell around the same editor the server serves, so there is
exactly one editor and the two cannot drift apart. It remains reachable at
`http://127.0.0.1:8770/editor` in a browser if you prefer.

Everything is stored in `shortcuts.json`, which is plain and safe to hand-edit.

### Action types

| Type | Fields | Does |
|---|---|---|
| `app` | `target`, `args`, `cwd` | Launches a program, document or folder |
| `aumid` | `target` | Launches a Microsoft Store / MSIX app by AppUserModelID |
| `urls` | `targets` (list), `new_window`, `browser`, `profile` | Opens a website group, by default in its own browser window |
| `hotkey` | `keys`, `repeat` | Sends keystrokes to the focused window |
| `text` | `text` | Types a literal string |
| `command` | `target` | Runs a CMD command |
| `powershell` | `target` | Runs a PowerShell command |
| `awake` | `state` (`on`/`off`/`toggle`) | Stops the PC sleeping or blanking the display |
| `wake_display` | — | Switches a sleeping display back on |
| `power` | `mode` (`shutdown`/`restart`/`logoff`/`abort`), `delay` | Shuts down, restarts, signs out, or cancels a pending one |
| `close_all` | `keep`, `only` | Asks open applications to close (WM_CLOSE, never a kill) |
| `macro` | `events`, `speed` | Replays a recorded keyboard/mouse macro |

A button may also carry `"confirm": true` (or a question string), which makes
the phone ask before running it. The phone app supplies a `WebChromeClient`
for this: without one Android's WebView answers `window.confirm()` with `false`
and shows nothing, so a confirmed button would silently do nothing.
| `chain` | `steps` (list of the above, plus `delay` and `notify`) | Runs them in order |

A chain stops at the first failing step unless that step sets
`"continue_on_error": true`. Chains are capped at 50 steps and 120 seconds.

### Hotkey names

Modifiers `ctrl shift alt win`, combined with `+`. Named keys include
`enter esc tab space backspace delete insert home end pageup pagedown`,
`left up right down`, `f1`–`f24`, and the media keys
`media_play_pause media_next media_prev volume_up volume_down volume_mute`.

```json
{ "type": "hotkey", "keys": "volume_up", "repeat": 4 }
```

---

## Rebuilding the Android app

```bash
powershell -ExecutionPolicy Bypass -File android/build_apk.ps1 -Install -Launch
```

No Gradle and no Android Studio: the script drives `aapt2 → javac → d8 →
zipalign → apksigner` directly, and the whole APK is about 17 KB. The server
token is baked in as a string resource at build time, so rotating the token
means deleting `.state/token.txt`, restarting the server, and rebuilding.

Because the app is signed with a local self-signed key, replacing a copy signed
by a *different* key needs `adb uninstall com.phonedeck.shell` first.

---

## Things worth knowing

**The phone's WebView is Chromium 71** (2018) and has never been updated
through the Play Store. `web/style.css` is written against that baseline
deliberately — no `inset`, no `aspect-ratio`, and no flexbox `gap`, all of
which are missing there. Test UI changes on the device, not just in desktop
Chrome. Updating *Android System WebView* from the Play Store would lift this,
but the CSS does not depend on you doing so.

**Only landscape forces a viewport-height body.** Pinning `height: 100%` on
`html, body` globally makes `<body>` the scroll container in portrait instead
of the document, which breaks scrolling in quiet ways. The rule lives inside
the landscape media query for that reason.

**Launched apps are raised deliberately.** Windows stops background processes
from stealing focus, and this server is a windowless `pythonw` process that
never has the foreground, so anything it launched opened *behind* the current
window. `AllowSetForegroundWindow` does not help — it is only granted to a
process that already has the foreground. `server/foreground.py` instead
attaches to the foreground thread's input queue, which makes
`SetForegroundWindow` legal, and finds the target by diffing the visible
top-level windows before and after the launch. A step can opt out with
`"foreground": false`, or steer the search with `"window_hint"`.

**Hotkeys cannot reach elevated windows.** Windows' UIPI silently discards
synthetic input aimed at a process running at a higher integrity level. If a
hotkey does nothing while an admin app is focused, run PhoneDeck elevated too.
The same applies to ending an elevated process from the process list.

**The drawer button sits well clear of the bottom edge.** In immersive mode
Android swallows the first touch inside the navigation-bar strip in order to
reveal the bar, so a control placed there never receives its click.

**Battery.** A phone held at 100% on a charger indefinitely will swell over
time. Consider charge limiting, or at least keep it somewhere that would not
matter.

---

## Debugging on the device

The app enables WebView remote debugging, so JavaScript can be evaluated in the
phone's browser from the PC:

```bash
python tools/devtools.py "document.getElementById('drawer').hidden"
```

This is how the drawer-positioning and touch-delivery problems were diagnosed;
it beats guessing from screenshots. Set `WEB_DEBUGGING = false` in
`MainActivity.java` to turn it off.

---

## Layout

```
run.py                  entry point: server + tray
editor_app.py           the standalone editor window
install_autostart.ps1   Startup, Start Menu and desktop shortcuts
assets/phonedeck.ico    application icon
shortcuts.json          your buttons (created on first run)
server/
  app.py                HTTP routes and auth
  stats.py              CPU / RAM / disk / network sampling
  sensors.py            temperatures and GPU, on a background thread
  tray.py               system-tray icon and menu (optional)
  icons.py              real application logos for the top-bar slots
  actions.py            the shortcut engine
  hotkeys.py            SendInput via ctypes, no dependencies
  foreground.py         brings launched apps to the front
  power.py              keep-awake, display wake, shutdown, close-all
  browsers.py           resolves the default browser for website groups
  claude.py             Claude activity state
  macros.py             record and replay input macros
  bridge.py             adb watchdog: tunnel, wake, launch
  config.py             paths, token, default shortcuts
web/
  index.html app.js style.css        the phone dashboard
  editor.html editor.js editor.css   the shortcut editor
android/
  build_apk.ps1         Gradle-free APK build
  java/…/MainActivity.java
tools/devtools.py       evaluate JS in the phone's WebView
```
