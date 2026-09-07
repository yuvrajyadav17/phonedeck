# Rooting the Realme 1 (CPH1859) for HID unlock

This is the one-time setup that lets the phone type your PIN at the Windows
lock screen. The goal of rooting here is narrow: it unlocks the ability to
create a **USB HID keyboard** on the phone, whose keystrokes reach the lock
screen because they arrive as real hardware input.

**Your device is a good candidate** — verified, not assumed:

| Fact | Value | Why it matters |
|---|---|---|
| Kernel HID gadget | `CONFIG_USB_CONFIGFS_F_HID=y` | The phone *can* become a keyboard |
| Layout | A-only (no A/B slots) | Simple `fastboot flash boot` |
| Bootloader | Unlocked (OEM) | Flashing allowed, and recoverable |
| Firmware | `CPH1859EX_11_C.50` | Determines the correct boot image |

---

## What is already done

* Kernel capability confirmed.
* Official **Magisk v30.7** installed on the phone (verified against GitHub's
  own SHA-256; the APK is in `.state/Magisk-v30.7.apk`).
* `tools/flash_magisk.ps1` written — the guarded flash step.

## The one thing you must fetch: the stock boot image

Magisk roots by patching **your firmware's exact** `boot.img`. A mismatched one
bootloops the phone, and I have no way to verify a download truly matches
`C.50` — so I will not hand you a link and risk your device. You get this file;
I do the rest.

You need the `boot.img` from firmware **`CPH1859EX_11_C.50`** (must match your
installed build exactly — check with `adb shell getprop ro.build.display.id`).

Realme ships firmware as an encrypted `.ozip`. To get `boot.img` out of it:

1. Download the `CPH1859EX_11_C.50` stock firmware `.ozip` (Realme's firmware
   pages or a reputable archive — verify the version string matches).
2. Decrypt and unpack it with an open-source tool such as
   **`bkerler/oppo_decrypt`** (`ozipdecrypt.py`), which turns the `.ozip` into
   an extractable image containing `boot.img`.

Keep that `boot.img` safe — it is **also your recovery image** if anything goes
wrong.

---

## Then, mostly hands-off

### 1. Patch the boot image (on the phone — a few taps)

* Copy your stock `boot.img` to the phone (Downloads is fine), or run:
  `adb push boot.img /sdcard/Download/`
* Open **Magisk** → **Install** → *Select and Patch a File* → pick `boot.img`.
* Magisk writes `magisk_patched-XXXXX.img` to `/sdcard/Download/`.

### 2. Tell me — I pull it and flash it

Once patched, I run:

```
adb pull /sdcard/Download/magisk_patched-XXXXX.img .state\
powershell -ExecutionPolicy Bypass -File tools\flash_magisk.ps1 -Image ".state\magisk_patched-XXXXX.img"
```

The script reboots to the bootloader, waits for fastboot, and flashes. It
**pauses and asks you to type YES** right before it writes the boot partition —
that single confirmation is yours, because it is the point of no return.

### 3. Verify

Phone boots, open Magisk → if it says **Installed: 30.7**, root is live. Tell
me, and I build the HID unlock immediately.

---

## If it bootloops (recoverable)

Because the bootloader is unlocked, a bad boot image is never fatal:

```
adb reboot bootloader          # or hold Power+VolUp, then plug in
fastboot flash boot boot.img   # your STOCK image from above
fastboot reboot
```

You are back to exactly where you started. This is why keeping the stock
`boot.img` matters.

---

## What gets built after root

* A `hid` module: sets up a configfs USB gadget with a keyboard function
  alongside adb (so the tunnel keeps working), and writes HID reports to
  `/dev/hidg0`.
* An **Unlock PC** action: when the PC is locked, PhoneDeck (still running in
  the background) tells the phone over adb to type the PIN as real keystrokes.
* The PIN is stored in gitignored `.state/`, never in the repo. Whoever holds
  both your phone and your PC could unlock it — the accepted trade-off of any
  tap-to-unlock.
