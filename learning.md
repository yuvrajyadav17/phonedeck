# PhoneDeck — the complete guide

Everything you need to run, change and extend the system, written to be read
top to bottom once and then dipped into later.

`README.md` is the technical summary. **This** file is the how-to.

---

## Contents

1. [How the whole thing works](#1-how-the-whole-thing-works)
2. [Starting, stopping, and the tray icon](#2-starting-stopping-and-the-tray-icon)
3. [Using the dashboard on the phone](#3-using-the-dashboard-on-the-phone)
4. [The editor](#4-the-editor)
5. [Adding a shortcut — every kind](#5-adding-a-shortcut--every-kind)
6. [The top bar: four app launchers](#6-the-top-bar-four-app-launchers)
7. [Finding the values you need](#7-finding-the-values-you-need)
8. [Chains: one tap, many steps](#8-chains-one-tap-many-steps)
9. [Editing the file by hand](#9-editing-the-file-by-hand)
10. [Troubleshooting](#10-troubleshooting)
11. [Changing the app itself](#11-changing-the-app-itself)

---

## 1. How the whole thing works

Three pieces:

```
   YOUR PC                                      YOUR PHONE
   ───────                                      ──────────
   PhoneDeck server (Python)                    PhoneDeck app
     ├─ serves the dashboard  ◄──── USB ────►     a thin shell that
     ├─ reads CPU/RAM/GPU/disk      cable         displays the dashboard
     ├─ runs your shortcuts
     └─ drives the phone over adb
```

Three ideas explain almost everything:

**The phone is a display, not a brain.** Every number you see is measured on
the PC and sent over. Every button you tap runs on the PC. The phone app is
about 150 lines whose only job is to show a web page full screen.

**The PC drives the phone, not the other way round.** When your PC starts, the
server waits for the phone on USB, opens a tunnel, wakes the screen, and
launches the app. That is why it comes up by itself, and why unplugging and
replugging recovers on its own.

**Nothing is on your network.** The server listens only on `127.0.0.1`. The
phone reaches it through `adb reverse`, which tunnels the phone's own
`localhost` to your PC's through the USB cable. Nobody else on your Wi-Fi can
see it, and every request additionally needs a token.

---

## 2. Starting, stopping, and the tray icon

### It starts by itself

The server is registered in your Startup folder, so it runs at every login. You
should not have to do anything.

### The tray icon

Look in the system tray (bottom-right, possibly under the `^` arrow) for the
blue PhoneDeck icon. That is the running server.

| Action | What it does |
|---|---|
| **Double-click** | Opens the editor |
| *Open editor* | Same |
| *Open dashboard in browser* | Shows the dashboard on your PC, handy for testing |
| *Phone: …* | Current connection state (not clickable) |
| *Wake phone and relaunch app* | Use if the phone screen is off or the app was closed |
| *Keep PC awake* | Tick it and the PC will not sleep or blank its screen |
| *Wake display* | Turns the monitor back on |
| *Lock PC* | Locks the session |
| *Quit PhoneDeck* | Stops everything |

### Starting it manually

If you quit it, reopen it from the Start Menu (**PhoneDeck Editor** starts the
server too), or run:

```bash
python run.py
```

### Turning autostart off

```bash
powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove
```

And to put it all back:

```bash
powershell -ExecutionPolicy Bypass -File install_autostart.ps1
```

---

## 3. Using the dashboard on the phone

### Three pages

**Swipe left and right** anywhere except the Disk I/O card, which keeps its own
swipe for the drives. Dots at the bottom show where you are.

**Page 1 — essentials.** What is worth seeing without touching anything: a
clock, the weather, whatever the PC is playing, and your notes and to-dos.

**Page 2 — the system.** CPU, RAM and GPU down the left, Network and Disk I/O
in the middle, the process list on the right with its **CPU / RAM** switch.

**Page 3 — downloads.** No swipe reaches it. The only way in is the chip in the
top bar, which itself appears only while something is actually downloading.
Swiping off it returns you where you were.

The system readout moved off the front deliberately: it is what you go looking
for when something is wrong, and it was taking the whole screen away from
things worth glancing at all day.

### The top bar

Uptime clock, CPU and GPU temperature, the Claude light, the four app
launchers, the download chip (only when downloading), the connection dot, the
microphone button, and the menu.

### Gestures

| Gesture | Effect |
|---|---|
| Swipe the **Disk I/O** card left or right | Page through drives C:, D:, E: |
| Tap the dots under it | Jump straight to a drive |
| **CPU / RAM** switch | Sort processes by that measure |
| **Hold** a process row | End that process (asks first) |
| Tap the **menu grid** | Open the shortcut drawer |
| Tap a **logo** in the top bar | Launch that app |

### Portrait

Rotate the phone and everything restacks into one scrolling page. Nothing is
lost. The app follows your phone's rotation lock, so lock it to landscape and
it will stay there even lying flat on the desk.

### What the connection dot means

| Colour | Meaning |
|---|---|
| Green "live" | Talking to the PC |
| Amber "retrying" | Missed a poll, trying again |
| Red "offline" | Lost the PC — check the cable, or use *Wake phone and relaunch app* |

---

### Weather

Comes from Open-Meteo: no API key, no account.

The coordinates are set explicitly in `server/config.py` (`WEATHER_LAT` /
`WEATHER_LON`). **Do not rely on the IP fallback** — it reports wherever your
ISP breaks out, which on this connection was about 160 km away. The fallback
only runs if both are left as `None`.

Open-Meteo answers for any coordinate by interpolating its forecast grid, so
asking for an exact point automatically gives you the nearest available data —
about 2 km away here. The grid point that answered comes back in the API as
`grid_lat` / `grid_lon` if you ever want to check.

The place name is only a label. It is reverse-geocoded once and cached in
`.state/location.json`; set `WEATHER_PLACE` in config to override it, or delete
the cache file to have it looked up again after changing coordinates.

### Now playing

Reads Windows' own media session — the same source the volume flyout uses — so
it works for Spotify, a browser tab, VLC, anything that registers a session. No
per-app integration.

It needs the split `winrt-*` packages listed in `requirements.txt`. The older
monolithic `winsdk` has no wheel for Python 3.14 and fails to build.

## 4. The editor

Open **PhoneDeck Editor** from the desktop, the Start Menu, or the tray.

```
┌───────────────┬──────────────────────────────┐
│ TOP BAR       │                              │
│  1 Claude     │   Properties of whatever     │
│  2 Comet      │   you selected on the left   │
│  3 Slack      │                              │
│  4 WhatsApp   │   • Label, icon, colour      │
│               │   • Action                   │
│ GROUPS        │   • Raw JSON (advanced)      │
│  Apps  Edit   │                              │
│  Media Web    │                              │
│                                              │
│ BUTTONS       │                              │
│  Notepad …    │                              │
└───────────────┴──────────────────────────────┘
```

**Groups** are the tabs in the phone's drawer. **Buttons** are the tiles inside
the selected group. **Top bar** slots are the four logos.

Workflow:

1. Click a group, then a button (or **+** to add one).
2. Change the label, icon and colour.
3. Pick an action type and fill in the fields.
4. Press **Test now** — it runs immediately on the PC, so you can see it work
   before committing.
5. Press **Save** (or Ctrl+S).

Changes reach the phone the next time you open the drawer. You do not need to
restart anything.

The **↑ ↓** arrows next to each group and button reorder them. Ordering in the
editor is the ordering on the phone.

---

## 5. Adding a shortcut — every kind

Pick the **Type** in the Action box. Here is each one, with a real example.

### 5.1 Launch a normal program

**Type:** `Launch app / file / folder`

| Field | Example |
|---|---|
| Path or command | `notepad.exe` |
| Arguments | *(blank)* |

The path can be:

* a bare command Windows knows — `notepad.exe`, `calc.exe`, `mspaint.exe`
* a full path — `C:\Program Files\Git\git-bash.exe`
* a path using environment variables — `%LOCALAPPDATA%\Programs\foo\foo.exe`
* a **folder** — `%USERPROFILE%\Downloads` (opens File Explorer)
* a **document** — `E:\notes\todo.txt` (opens in whatever handles .txt)

### 5.2 Launch a program with arguments

**Type:** `Launch app / file / folder`

Opening Comet on a specific profile:

| Field | Value |
|---|---|
| Path or command | `%LOCALAPPDATA%\Perplexity\Comet\Application\comet.exe` |
| Arguments | `"--profile-directory=Profile 3"` |

**Quote any argument containing a space.** `--profile-directory=Profile 3`
without quotes would be read as two separate arguments and silently ignored.
The editor keeps the quotes when it saves and shows them again when you reopen.

More useful browser arguments:

```
--incognito                          open a private window
--new-window https://example.com     force a new window, not a tab
--app=https://mail.google.com        open a site as its own window
```

### 5.3 Launch a Microsoft Store app

Store apps (Claude, Slack, WhatsApp, Calculator, Photos, Settings…) **cannot**
be launched by their path. They live in a folder whose name contains the
version number and changes with every update, and Windows blocks running them
from there directly.

They are launched by **AppUserModelID** instead — a permanent identifier.

**Type:** `Launch Microsoft Store app`

| Field | Example |
|---|---|
| Path or command | `91750D7E.Slack_8she8kybcnzg4!Slack` |

To find the AppUserModelID of any installed app, run this in PowerShell:

```powershell
Get-StartApps | Where-Object { $_.Name -match 'slack' }
```

It prints the name and the `AppID`. That `AppID` is what you paste. Drop the
`-match` filter to list everything:

```powershell
Get-StartApps | Sort-Object Name
```

**How do I know whether an app is a Store app?** If `Get-StartApps` shows an
AppID with an `!` in it, it is. If its path is under
`C:\Program Files\WindowsApps`, it is.

### 5.4 Website groups

**Type:** `Open website(s)`

A website group is just a button holding several sites. **One button = one
group**, its label is the group name, and you can have as many as you like —
add another button for another group. There is no fixed number.

Put one URL per line:

```
https://mail.google.com
https://calendar.google.com
https://github.com
```

Tap it and the whole group opens **in its own browser window**, separate from
whatever else you had open. That is what keeps groups apart: tap *Work* and its
sites land in one window, tap *Reading* and those land in another.

| Option | Meaning |
|---|---|
| **Open the group in its own browser window** | On by default. Untick it to add the sites as tabs to the window you already have |
| **Browser** | Leave blank for your default (currently Comet). Set a path to use a different browser for this group |
| **Profile** | Chromium profile *directory* — see [section 7](#which-chromium-profile-is-which). Lets one group open in your work profile and another in your personal one |

So a typical setup might be:

| Button | Sites | Profile |
|---|---|---|
| Work ☕ | mail, calendar, Linear | `Profile 3` |
| Reading 📚 | HN, arXiv | *(default)* |
| Admin 🧾 | bank, invoicing | `Default` |

Three buttons, three windows, each with its own set of sites — and you decide
every part of it.

> **Note on browser tab groups.** Chromium's coloured, named tab groups cannot
> be created from outside the browser: there is no command-line switch and no
> supported API for them, only an extension running inside the browser could.
> A dedicated window is the practical equivalent, and is what this does.

### 5.5 Send a hotkey

**Type:** `Send hotkey`

| Field | Example |
|---|---|
| Keys | `ctrl+shift+esc` |
| Repeat | `1` |

The keystroke goes to **whatever window is focused on your PC** — which is what
makes copy, paste and volume work from the phone.

**Modifiers:** `ctrl` `shift` `alt` `win`, joined with `+`.

**Named keys:**

```
enter  esc  tab  space  backspace  delete  insert
home   end  pageup  pagedown
left   up   right  down
f1 … f24
capslock  numlock  scrolllock  printscreen  pause  apps
media_play_pause   media_next   media_prev   media_stop
volume_up   volume_down   volume_mute
browser_back  browser_forward  browser_refresh  browser_home
```

Letters, digits and punctuation are written literally: `a`, `7`, `,`.

**Repeat** matters for volume — one press is a barely audible step, so use 4
or 5.

Useful examples:

```
ctrl+c              copy
ctrl+v              paste
ctrl+shift+t        reopen closed browser tab
alt+tab             switch window
win+d               show desktop
win+shift+s         screenshot tool
ctrl+shift+esc      Task Manager
```

### 5.6 Type a block of text

**Type:** `Type text`

Types the text into the focused window, character by character. Good for email
addresses, boilerplate replies, long paths.

It is typed literally regardless of your keyboard layout, so symbols come out
right.

### 5.7 Run a command

**Type:** `Run CMD command` or `Run PowerShell`

| Type | Example |
|---|---|
| CMD | `ipconfig /flushdns` |
| PowerShell | `Get-Service Spooler \| Restart-Service` |

The command runs **hidden** — no console window appears. If it fails, the phone
shows the error text. If it succeeds, the phone shows the first part of its
output, which is a neat way to check something quickly.

Commands are given 60 seconds before they are killed.

### 5.8 Power and session control

These live in the **System** group.

| Button | What it does |
|---|---|
| **Lock PC** 🔒 | Locks the session, same as Win+L |
| **Keep Awake** ☕ | Toggles a hold that stops the PC sleeping or blanking the display |
| **Wake Screen** 💡 | Turns the monitor back on |
| **Close All** ✖ | Asks every open application to close |
| **Restart** 🔁 | Restarts, after a 15 second grace period |
| **Shut Down** ⏻ | Shuts down, after a 15 second grace period |
| **Cancel Shutdown** ⛔ | Calls off a pending shutdown or restart |

**Close All** sends each window the same `WM_CLOSE` message the X button sends.
Nothing is force-killed, so anything with unsaved work still prompts you to
save. File Explorer, the desktop shell and PhoneDeck itself are never asked to
close, or you would be left with a blank screen.

**Shut Down** and **Restart** wait 15 seconds before acting. That delay is why
**Cancel Shutdown** exists — tap it within the window and nothing happens.
To go immediately, set `"delay": 0` in the action.

The three destructive buttons **ask before running**. See
[Confirmation](#confirmation) below.

**Keep Awake** is a switch: tap once to hold the machine awake, tap again to
release it. Useful while you are watching the dashboard and not touching the
keyboard — your display is set to switch off after 30 minutes of idle, and this
suspends that. It survives until you turn it off or quit PhoneDeck.

**Wake Screen** works when the display has gone dark but the session is *not*
locked. It nudges the mouse by zero pixels, which counts as activity without
moving your pointer or pressing anything.

Both are also on the tray menu.

#### Confirmation

Any button can ask before it runs. Tick **"Ask on the phone before running"**
in the editor, or set `"confirm": true` on the button by hand. For a custom
question, use a string instead:

```json
{ "id": "shutdown", "label": "Shut Down", "confirm": "Shut down this PC?", ... }
```

Worth using on anything you would regret double-tapping.

#### Why there is no "Unlock PC"

There cannot be one, and it is worth knowing exactly why — the obvious idea of
"just type the PIN for me" does not work, and not because of a missing feature.

Windows runs more than one *desktop* inside your session. Your programs live on
one called `Default`. The lock screen runs on a separate one called `Winlogon`,
and when you lock the machine, keyboard and mouse input is switched over to it.

`SendInput` — the API PhoneDeck uses for every hotkey — can only deliver input
to the desktop the calling thread is attached to. A program running as you
cannot attach to `Winlogon`; the call to even *look* at it comes back "access
denied". So keystrokes aimed at the lock screen are not ignored, they never
arrive anywhere at all. This is deliberate: it is precisely what stops malware
from typing someone's PIN.

The only thing on the other side of that boundary is a **Credential Provider**:
a system component registered with Winlogon, installed with administrator
rights, running as SYSTEM. Even then it has to supply real credentials, which
means keeping your password somewhere a program can read it — giving away the
security the lock exists to provide. PhoneDeck stores no password and has no
such component.

Windows provides `LockWorkStation` and deliberately no counterpart.

The only supported way to unlock without the keyboard is a **Credential
Provider**: a system component registered with Winlogon, installed with
administrator rights, that still has to supply real credentials. That means
keeping your password where a program can read it, which trades away the
security the lock exists to provide.

So the practical answer is to avoid needing the unlock:

* **Keep Awake** while you are at the desk, so it never blanks.
* **Wake Screen** when the display is off but the session is still open.
* If it *is* locked, Windows Hello (face, fingerprint or PIN) is the fast way
  back in.

---

## 5A. The Claude tracker

The top bar carries a **CLAUDE** light, and the bottom of the centre column
shows how many tokens have been spent.

### What the colours mean

| Colour | State | Meaning |
|---|---|---|
| ⚪ Grey | `off` | No Claude session running |
| 🟢 Green | `idle` | Session open, Claude waiting for you |
| 🔵 Blue *(pulsing)* | `working` | Claude is processing a turn |
| 🟠 Amber | `asking` | Claude wants an answer — a permission prompt or a question |
| 🔴 Red | `error` | The turn ended on an API error |
| 🟣 Purple | `limit` | A usage or rate limit was hit |

If several sessions are open, the light shows the one that most needs you:
asking beats limit beats error beats working beats idle.

There is no "Claude" label beside it — the colour and the one word say it.

### Where the state comes from

Two sources, combined:

* **Which sessions exist** comes from Claude's own registry in
  `~/.claude/sessions`. This is what makes the light correct the moment Claude
  is opened, and after PhoneDeck restarts. A session that is simply sitting
  there reads as idle rather than off.
* **What each session is doing** comes from Claude Code's **hooks**, which POST
  each event straight to PhoneDeck. Only infrequent events are hooked — prompt
  submitted, notification, permission request, stop, failure, session start and
  end — so nothing is added to the cost of individual tool calls.

```bash
python tools/claude_hooks.py --status      # what is installed
python tools/claude_hooks.py --install     # add them
python tools/claude_hooks.py --remove      # take them out again
```

They live in `~/.claude/settings.json`, and the file is backed up before every
change. **New sessions pick them up**; a session already running keeps the
hooks it started with.

Three details worth knowing:

* The hook endpoint is **unauthenticated and always answers 200**. Claude
  treats a 4xx from a hook as an instruction to block the action, so a
  rejected request could stall a real session. It only moves a status light,
  and it listens on loopback only.
* If PhoneDeck is not running the POST is refused instantly — Claude is not
  left waiting.
* A session that dies without saying so (crashed, killed) is dropped by
  cross-checking Claude's own live-session registry, so the light cannot get
  stuck showing a session that ended.

### Why there is no usage/limit readout

There was one, showing tokens spent. It has been removed, because it could not
show the thing that actually matters.

The session and weekly **percentages** Claude Code shows in `/usage` come from
the API. They are not written to disk anywhere — not in `~/.claude`, not in the
transcripts — and there is no `claude usage` subcommand; `/usage` only exists
inside an interactive session. So nothing running outside Claude can read your
real limits.

Raw token counts *were* measurable, but a number that is not the limit is not
worth the space on a small screen. The light stays; the numbers went.

If Claude Code ever exposes limits to a hook or a command, this becomes a
twenty-line addition.

---

## 5B. Recorded macros

**Type:** `Recorded macro`

Press **Record** in the editor, do the thing on your PC, press **Stop**. Every
keystroke, click and drag is captured with its timing, and the button replays
it exactly.

| Field | Meaning |
|---|---|
| **Record / Stop** | Captures until stopped |
| **Speed ×** | `1` replays at the original pace; `2` is twice as fast, `0.5` half |

### What is and is not captured

* Keystrokes, mouse clicks, drags and the scroll wheel — all with real timing.
* **Idle mouse movement is skipped.** Only clicks and movement *while a button
  is held* are kept, so a drag stays smooth without recording thousands of
  pointless points.
* **Input PhoneDeck itself generates is skipped.** Windows flags synthesised
  events, so replaying a macro cannot be recorded back into another one.

### Two things to know before you rely on it

**Recording captures everything you type, system-wide, until you press Stop.**
Do not type a password while it is running — it would be stored, in plain text,
in `shortcuts.json`.

**Replay clicks fixed screen positions.** If the window it used has moved or
resized, the macro clicks the wrong place. Macros are most reliable when they
are mostly keyboard, or when the target window opens in a predictable spot.
This is true of recorded macros generally, not something PhoneDeck can fix.

### Stopping from the phone

The Stop button in the editor is itself a click on the PC, so that click is
trimmed off the end automatically. If you would rather not have the trim guess
for you, stop the recording from the phone instead — a tap there touches
nothing on the PC, so nothing needs removing.

The same applies to starting: `POST /api/macro/record/start` and
`/api/macro/record/stop`, so a drawer button can drive it too.

### Elevated windows

Like hotkeys, a replayed macro cannot reach a window running as administrator.
Windows discards synthetic input aimed at higher-privileged processes.

---

## 5C. Sound: listening and dictating

### Playing PC audio through the phone

Tap **listen** on the PLAYING card. The PC's output is captured and streamed
down the USB cable, and the phone plays it.

Latency is about a fifth of a second -- fine for music, poor for lip-sync on
video. Audio is uncompressed, because the link is a cable where bandwidth is
free and a codec would only add delay. Capture runs only while something is
listening.

**On using both speakers:** not possible on the Realme, for two separate
reasons. Android reports one earpiece and one loudspeaker on the CPH1859 -- the
earpiece is a call receiver, not a second speaker, so there is no stereo pair to
drive. And Android routes media audio to one output at a time; there is no API
for an app to play out of the earpiece and the loudspeaker together. The
loudspeaker alone is what you get, and it is the better of the two anyway.

The stream itself is stereo regardless. Downmixing on the PC only threw
information away: Android already folds stereo down to whatever speakers the
device actually has, and doing it first made a phone with a real stereo pair
impossible to serve.

### Why the stream used to arrive in chunks

Three separate faults, all of which had to go. Worth reading before touching
anything in this path, because two of them are invisible from the code.

**1. The process list was blocking the audio.** This is the one that mattered
and the one nobody would guess. `/api/stats` took **1.06 seconds**, and 96% of
that was `psutil_windows.proc_info` -- a C call costing about 5 ms per process,
which does **not release the GIL**. Three hundred processes is over a second in
which no other thread in the interpreter can run at all, including the one
feeding audio to the phone. Measured at the socket: gaps between 43 ms frames
had a p95 of 104 ms and a maximum of 159 ms, while the same capture measured on
its own was steady at 41.8 ms p95. The server, not the network and not the
phone, was making the audio bursty.

Threads cannot fix this. A thread blocked inside a C call that holds the GIL
blocks every other thread by definition. A second *process* can, because it has
a GIL of its own, so the scan moved to `server/procscan.py` and reports back
over a pipe on a two-second cadence. `/api/stats` went from 1062 ms to 27 ms,
socket jitter from 104 ms p95 to 43.8, and the CPU percentages got *better*,
because psutil now has a fixed interval to divide by instead of however long
the phone took between requests.

**2. Playback was on the main thread.** A `ScriptProcessorNode` runs its
callback on the page's main thread, so it competed with the dashboard's own
rendering; measured main-thread stalls on this phone reach 54 ms, and any stall
longer than the callback period is an audible hole. The fix is an
`AudioWorkletProcessor`, which runs on the audio render thread and cannot be
starved by anything the page draws.

The reason it was not used in the first place was a wrong assumption -- that
Chromium 71 predates AudioWorklet. It does not: AudioWorklet shipped in Chrome
66, and the WebView on this phone reports it present. **Check the device before
ruling a capability out**; the same mistake produced the CSS baseline earlier
in this document, and there it was right for a different reason.

**3. The jitter buffer re-armed too low.** After a dropout it resumed at 60 ms
of cushion -- barely one 43 ms frame -- so the next jitter emptied it again.
That is a feedback loop: 114 underruns in 50 seconds, which is exactly what
"playing in chunks" sounds like.

It now waits for the whole cushion before resuming, and the cushion is not a
fixed number: it grows by 60 ms each time the buffer runs dry and gives back
4 ms per quiet second, so it settles wherever the device needs it. On the
Realme it walks down to its 120 ms floor and stays there. A faster phone ends
up with less delay without anyone choosing a number for it.

There is also a **clock-drift** correction, which nothing on the old path had.
The PC samples at "48000" and the phone plays at "48000", but the crystals
differ by tens of parts per million -- seconds of error per hour -- so the
buffer would slowly fill or drain and eventually break however well it was
sized. Playback speed is nudged by at most 0.5%, eight cents, well under
audibility, to hold the buffer at its target.

Result, streaming a test tone for 80 seconds with the dashboard live:
**zero underruns**, buffer steady between 118 and 141 ms, output peak matching
the source amplitude.

`window.__audioStats` carries the live figures -- fill, target, underruns,
output peak -- so this is measurable rather than arguable.

### Is Python the problem?

It was reasonable to ask, and the answer is a useful one: **no, and the
measurement says so plainly.** The whole capture loop -- WASAPI read, clip,
convert, hand to the socket -- costs **0.18% of one core**. Rewriting it in C
would save around a fiftieth of one percent of a CPU.

What *did* hurt was Python-specific, but not Python's speed: the GIL, and one
library call that holds it for 5 ms at a time. The fix was to move that call
out of the interpreter, not to leave the language. The general shape of it
holds well beyond this project -- when a runtime looks slow, measure before
rewriting, because the cost is usually one call in one place, and a rewrite
carries every one of those calls along with it.

### Dictating to the PC

Tap the **microphone** button in the top bar, speak, tap it again. What you say
is typed into whichever window has focus on the PC.

Recognition runs **offline** on the PC using Vosk -- no API key, no internet, and
no audio leaves the machine. The model lives in `.tools/` and is not in the
repository; see `requirements.txt` for the download.

It types rather than pretending to be a microphone device. Making the phone
appear as a real Windows input device would need a virtual audio driver
installed at kernel level, with administrator rights and a reboot; typing the
recognised words needs none of that and is what dictation is actually for.

Two things the Android app needs for this, both easy to get wrong:

* `RECORD_AUDIO` **and** `MODIFY_AUDIO_SETTINGS`. Without the second the
  WebView refuses to open any microphone and `getUserMedia` fails with a bare
  `NotReadableError`; the real reason only appears in logcat.
* A `WebChromeClient.onPermissionRequest` that grants the request. Without it
  the WebView denies the page's microphone request silently.

---

## 6. The top bar: four app launchers

The four logos next to the temperatures. They are edited exactly like any other
shortcut, but they show the application's **real icon** instead of an emoji.

### Changing what a slot launches

1. Open the editor.
2. Click the slot under **TOP BAR**.
3. Set the **Label** (this is the tooltip).
4. Set the **Action** — usually `Launch Microsoft Store app` or
   `Launch app / file / folder`, exactly as in section 5.
5. Save.

### Where the icon comes from

Leave **Icon source** blank and PhoneDeck extracts the icon from the `.exe` the
action launches. That works for ordinary programs and is usually fine.

For **Store apps** there is no `.exe` to point at, and their own shipped logo is
much crisper anyway. Use this syntax:

```
appx:<PackageName>|<relative path to the image>
```

Real examples, all currently in use:

```
appx:Claude|Assets\Square150x150Logo.scale-200.png
appx:91750D7E.Slack|Assets\SlackAppList.targetsize-512_altform-unplated.png
appx:5319275A.WhatsAppDesktop|Assets\AppList.targetsize-256_altform-unplated.png
```

To find the right asset for a new app, list its Assets folder:

```powershell
$p = Get-AppxPackage -Name '*slack*' | Select-Object -First 1
$p.Name                                    # the PackageName for appx:
Get-ChildItem (Join-Path $p.InstallLocation 'Assets') -Filter *.png |
  Sort-Object Length -Descending | Select-Object -First 10 Name
```

Pick the biggest sensible one. Some naming conventions:

| Suffix | Meaning |
|---|---|
| `targetsize-512` | 512×512 — the crispest |
| `altform-unplated` | Logo **without** its background tile — best on the dark bar |
| `altform-lightunplated` | The variant meant for light backgrounds — usually avoid |
| `scale-200` | Double-density version of the base size |

You can also point Icon source at any `.png`, `.ico` or `.exe` on disk:

```
E:\icons\my-app.png
C:\Program Files\Foo\foo.exe
```

### Emptying a slot

Select it and press **Clear this slot**. It becomes a dashed placeholder.

### Adding a fifth slot

Change `SLOT_COUNT` in **both** `web/app.js` and `web/editor.js`, then reload.
The editor pads your saved config up to the new number, so nothing is lost.

---

## 7. Finding the values you need

A cheat sheet for the four things you will look up most.

### Where is a program installed?

If it is running, ask:

```powershell
Get-Process slack, comet, code | Select-Object -Unique ProcessName, Path
```

Or read it out of its Start Menu shortcut:

```powershell
$sh = New-Object -ComObject WScript.Shell
Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Recurse -Filter *.lnk |
  Where-Object { $_.BaseName -match 'notion' } |
  ForEach-Object { $l = $sh.CreateShortcut($_.FullName)
                   "{0}`n  target: {1}`n  args  : {2}" -f $_.BaseName, $l.TargetPath, $l.Arguments }
```

That also reveals the **arguments** the normal shortcut uses, which is often
exactly what you want to copy.

### What is an app's AppUserModelID?

```powershell
Get-StartApps | Where-Object { $_.Name -match 'whatsapp' }
```

### Which Chromium profile is which?

Chrome, Edge and Comet store profiles in folders called `Default`, `Profile 1`,
`Profile 2`… which are **not** the names you see in the browser. To map them:

```powershell
$ls = "$env:LOCALAPPDATA\Perplexity\Comet\User Data\Local State"
(Get-Content $ls -Raw | ConvertFrom-Json).profile.info_cache.PSObject.Properties |
  ForEach-Object { "dir='{0}'  name='{1}'" -f $_.Name, $_.Value.name }
```

Swap the path for Chrome or Edge:

```
%LOCALAPPDATA%\Google\Chrome\User Data\Local State
%LOCALAPPDATA%\Microsoft\Edge\User Data\Local State
```

Then use the **directory** name in the argument:
`"--profile-directory=Profile 3"`.

### What is my access token?

```
E:\Phone Project\.state\token.txt
```

You only need it to open the dashboard in a browser manually:
`http://127.0.0.1:8770/?t=<token>`. The editor and the phone app handle it for
you.

---

## 8. Chains: one tap, many steps

**Type:** `Chain of steps`

A chain runs steps in order. Each row is a step: pick its type on the left and
put its value on the right.

Step types are the same as the actions above, plus two that only make sense
inside a chain:

| Step | Value means | Purpose |
|---|---|---|
| `delay` | milliseconds | Wait for something to finish opening |
| `notify` | a message | Show text on the phone when it reaches this point |

### Example: start your work setup

```
app          C:\Program Files\Git\git-bash.exe
delay        800
urls         https://github.com  https://linear.app
delay        500
aumid        91750D7E.Slack_8she8kybcnzg4!Slack
notify       Work setup ready
```

### Example: free up disk space

```
powershell   Get-ChildItem $env:TEMP -Recurse -EA SilentlyContinue | Remove-Item -Recurse -Force -EA SilentlyContinue
delay        300
notify       Temp folder cleared
```

### Rules

* A chain **stops at the first step that fails**, and the phone tells you which
  one. To let a step fail without stopping the chain, add
  `"continue_on_error": true` to it in the Raw JSON box.
* Maximum 50 steps, and the whole chain must finish within 120 seconds.
* `delay` is capped at 10 seconds per step.

### Tip: use delays

Applications need a moment before they will accept a hotkey. If a chain opens
an app and then sends it keys, put a `delay` of 500–1500 ms between them, or
the keystroke arrives before the window exists and goes somewhere else.

---

## 9. Editing the file by hand

Everything lives in `shortcuts.json` in the project folder. The editor writes
it; you can too. Its shape:

```json
{
  "version": 1,
  "topbar": [
    {
      "id": "slot1",
      "label": "Claude",
      "icon_source": "appx:Claude|Assets\\Square150x150Logo.scale-200.png",
      "action": { "type": "aumid", "target": "Claude_pzs8sxrjxfjjc!Claude" }
    }
  ],
  "groups": [
    {
      "id": "apps",
      "name": "Apps",
      "icon": "🖥",
      "buttons": [
        {
          "id": "notepad",
          "label": "Notepad",
          "icon": "📝",
          "color": "#4c8dff",
          "action": { "type": "app", "target": "notepad.exe" }
        }
      ]
    }
  ]
}
```

### Every action field

| Type | Fields |
|---|---|
| `app` | `target`, `args` (list), `cwd` |
| `aumid` | `target` (the AppUserModelID) |
| `urls` | `targets` (list), `new_window` (default true), `browser`, `profile` |
| `hotkey` | `keys`, `repeat` |
| `text` | `text` |
| `command` | `target` |
| `powershell` | `target` |
| `awake` | `state`: `"on"`, `"off"` or `"toggle"` |
| `wake_display` | *(none)* |
| `power` | `mode`: `"shutdown"`, `"restart"`, `"logoff"` or `"abort"`; `delay` in seconds |
| `close_all` | `keep` (list of processes to spare), `only` (list to close instead of everything) |
| `chain` | `steps` (list of any of the above, plus `delay` with `ms`, and `notify`) |

Two extras accepted by `app`, `aumid` and `urls`:

| Field | Effect |
|---|---|
| `"foreground": false` | Do **not** bring the launched app to the front |
| `"window_hint": "slack"` | Help PhoneDeck find the window to raise, if it guesses wrong |

Rules that will save you time:

* **`id` must be unique across the whole file.** It is how the phone asks for a
  button.
* `"confirm": true` on a button makes the phone ask first; a string is used as
  the question.
* Backslashes must be doubled in JSON: `C:\\Users\\me\\file.txt`.
* Icons are just emoji characters — paste any you like.
* `color` is the stripe across the top of the tile.

After hand-editing, the phone picks it up next time you open the drawer. If you
break the JSON, the editor will say so rather than silently losing your work.

---

## 10. Troubleshooting

### The phone shows "Waiting for the PC"

1. Is the cable in? It must be a **data** cable, not charge-only.
2. Is the tray icon there? If not, start PhoneDeck.
3. Unlock the phone — if a *"Allow USB debugging?"* dialog is showing, accept
   it and tick **Always allow from this computer**.
4. Tray → *Wake phone and relaunch app*.

### The dashboard says "offline" but the app is open

The page is still loaded; only its polls are failing. That happens when
PhoneDeck is not running on the PC, or the USB tunnel dropped. It reconnects on
its own as soon as the server answers again — start PhoneDeck, or unplug and
replug the cable.

The tunnel itself is now re-checked every few seconds rather than assumed to be
alive, because restarting the adb server silently drops every tunnel while
leaving the phone attached.

### It says "Webpage not available" and stays there

It should not any more. The app retries every 2.5 seconds and picks itself up
once the PC answers, with nothing to do on the phone.

If you are on a build from before that fix, this state was permanent: Android
fires `onPageFinished` for its *own* error page, the app read that as a
successful load, and the retry timer stood down. Rebuild with
`android/build_apk.ps1 -Install -Launch`.

### A launched app opens behind my other windows

It should not — PhoneDeck raises it deliberately. If a particular app resists,
add a hint so it can find the right window:

```json
{ "type": "app", "target": "...", "window_hint": "myapp" }
```

The hint is matched against the process name. To see what that is, launch the
app and run `Get-Process | Where-Object { $_.MainWindowTitle }`.

To deliberately launch something **without** stealing focus, set
`"foreground": false`.

### A hotkey does nothing

Almost always because the focused window is running **as administrator**.
Windows refuses synthetic keystrokes aimed at a program with higher privileges
than the sender. Either don't use the hotkey there, or run PhoneDeck as
administrator too (right-click `run.py` → Run as administrator).

The same applies to ending a process from the process list.

### CPU temperature shows `--`

Windows exposes no CPU temperature to ordinary programs. Install
[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
and run it **as administrator**; PhoneDeck picks it up automatically within a
couple of seconds. No restart, no configuration.

GPU temperature needs nothing — it comes from the NVIDIA driver.

### An icon in the top bar shows a letter instead of a logo

PhoneDeck could not find an image. Either the `icon_source` path is wrong, or
the app has no extractable icon. Check the path exists, and for Store apps
confirm the asset name with the PowerShell snippet in section 6.

### A Store app "launches" but nothing happens

The AppUserModelID is probably wrong. Confirm it with `Get-StartApps`. A
mistyped id is reported as an error on the phone, so if you saw a green
"launched…" message the id was valid and the app itself decided not to show a
window.

### I locked the PC from the phone and now I cannot unlock it

Nothing in PhoneDeck can unlock a locked session — see section 5.8 for why.
Sign in at the machine (Windows Hello is quickest), and use **Keep Awake**
rather than **Lock PC** if what you actually wanted was to stop the screen
going dark.

### Keep Awake does not seem to be doing anything

It is a silent hold, so there is nothing to see until the display *would* have
switched off. Check `.state\phonedeck.log` — it records `keep awake: on` and
`keep awake: off` every time the state changes. Note that `powercfg /requests`
will not show it unless you run that command as administrator.

### Something is wrong and I want to see why

```
E:\Phone Project\.state\phonedeck.log
```

Everything the server does is recorded there, including every window it raised.

### I want to start completely fresh

Delete `shortcuts.json` and restart PhoneDeck. It writes a new one with the
default buttons. (Your top-bar slots go back to the defaults too.)

---

## 11. Changing the app itself

### Changing the dashboard's appearance

Everything visual is in `web/style.css`. Edit it, then reload the phone — no
rebuild needed.

**One rule matters.** The phone's browser engine is **Chromium 71**, from 2018.
Three modern CSS features do not exist there and will silently break the
layout:

| Do not use | Use instead |
|---|---|
| `inset: 0` | `top: 0; right: 0; bottom: 0; left: 0` |
| `aspect-ratio` | an explicit `height` |
| `gap` in a **flex** container | margins (`gap` in **grid** is fine) |

Test on the phone, not just in desktop Chrome — desktop Chrome will happily
render things the phone cannot.

### Rebuilding the phone app

Only needed if you change `MainActivity.java` or the manifest:

```bash
powershell -ExecutionPolicy Bypass -File android/build_apk.ps1 -Install -Launch
```

About fifteen seconds. The APK is ~17 KB.

### Inspecting the phone's browser from the PC

The app has remote debugging on, so you can run JavaScript inside it:

```bash
python tools/devtools.py "document.title"
python tools/devtools.py "document.getElementById('drawer').hidden"
```

This is far more reliable than guessing from screenshots.

### Changing how often it updates

`STATS_POLL_MS` in `server/config.py` (default 1000 ms).

### Changing the port

`PORT` in `server/config.py`. Change it in `android/java/.../MainActivity.java`
too — the `HOST` constant near the top — then rebuild the APK.

---

## Where everything lives

```
E:\Phone Project\
├── run.py                   start the server + tray
├── editor_app.py            the editor window
├── shortcuts.json           YOUR BUTTONS  ← the file you care about
├── learning.md              this guide
├── README.md                technical summary
├── install_autostart.ps1    Windows shortcuts and autostart
├── assets/phonedeck.ico     app icon
├── server/                  the Python server
├── web/                     the dashboard and editor pages
├── android/                 the phone app and its build script
├── tools/devtools.py        inspect the phone's browser
└── .state/                  token, logs, cached icons  (not for editing)
```
