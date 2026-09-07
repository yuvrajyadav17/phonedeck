# Unlocking & rooting the Realme 1 (CPH1859) via mtkclient

Your device is **MT6771 (Helio P60)**, which mtkclient can unlock at the
MediaTek BROM level — *below* the locked bootloader, with no dependence on
Realme's (probably dead) In-Depth Test approval servers. It also **dumps your
authentic C.50 boot image straight off the phone**, so there is no untrusted
firmware download anywhere in this process.

> **This wipes the phone.** Unlocking force-erases userdata — unavoidable on
> any Android unlock. Back up anything on it first. Battery > 50%.

---

## Already done (verified)

* Chipset MT6771 confirmed; mtkclient has a dedicated `mt6771_payload.bin`.
* mtkclient cloned to `.tools/mtkclient`, all CLI deps installed, runs on
  Python 3.14.
* Magisk v30.7 already on the phone (survives until the wipe; reinstalled after).

## The three things only you can physically do

1. **Swap the USB driver with Zadig** (one-time, ~5 clicks). When the phone is
   in BROM mode Windows shows a *MediaTek USB Port*; pyusb needs the
   **libusb-win32** driver on it. Download Zadig (zadig.akeo.ie), and with the
   phone in BROM mode: Options → List All Devices → pick the MediaTek port →
   select **libusb-win32** → Replace/Install Driver.
2. **Enter BROM mode:** power the phone **off**, then hold **both Volume Up +
   Volume Down**, and while holding, plug the USB cable into the PC. The screen
   stays black — that is correct; BROM is a black-screen mode.
3. **Accept the wipe** — implicit in running the unlock command.

## What I run once the phone is in BROM (I can drive these)

All from `E:\Phone Project\.tools\mtkclient`:

```
# 1. Dump YOUR authentic C.50 boot image (nothing is written)
python mtk.py r boot .state\stock_boot_C50.img

# 2. Unlock the bootloader (THIS WIPES USERDATA)
python mtk.py da seccfg unlock

# 3. (after patching, below) flash the Magisk-patched boot
python mtk.py w boot .state\magisk_patched.img
```

`mtk.py` waits with a "handshake" prompt; you plug the phone in (step 2 above)
while it waits, and it catches the BROM.

## Full order of operations

| # | Who | Action |
|---|---|---|
| 1 | you | Back up the phone. |
| 2 | you | Zadig driver swap (phone in BROM). |
| 3 | me | `mtk.py r boot` → dumps `stock_boot_C50.img` (your recovery image too). |
| 4 | me | `mtk.py da seccfg unlock` → **wipes**, bootloader now unlocked. |
| 5 | you | Phone reboots to first-time setup. Re-enable Developer Options + USB debugging. |
| 6 | me | Reinstall Magisk, re-run `install_autostart.ps1` so PhoneDeck comes back. |
| 7 | you | Magisk → Install → *Select and Patch a File* → pick `stock_boot_C50.img`. |
| 8 | me | Pull the patched image, `mtk.py w boot` (or `fastboot flash boot`, now that it is unlocked). |
| 9 | you | Boot up, open Magisk → *Installed: 30.7* = rooted. |
| 10 | me | Build the HID gadget + **Unlock PC** action. |

## Risks & recovery

* **BROM handshake may need retries** — timing of the key-combo + plug is
  finicky. If mtkclient does not catch it, unplug, wait, try again. Some units
  need the cable plugged *at the moment* the handshake prompt appears.
* **You always have your stock boot** (`stock_boot_C50.img` from step 3). If a
  patched flash misbehaves: `python mtk.py w boot .state\stock_boot_C50.img`.
* **If BROM is SLA/DAA-protected** (unlikely on MT6771/2018), mtkclient will say
  so and need a `payload` step — I handle that if it comes up.
* Re-locking later also wipes; there is no reason to re-lock.

## Why not Realme's official In-Depth Test?

It contacts Realme's servers for per-device approval. For a 2018 model in 2026
that approval path is very likely discontinued, and the APK itself comes from
forums I cannot verify. mtkclient is open source (auditable), works offline at
the chip level, and — crucially — sources the boot image from your own device
instead of a stranger's upload.
