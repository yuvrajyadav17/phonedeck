"""Real application logos for the top-bar shortcuts.

An emoji stands in for an app; the actual icon identifies it instantly, which
is the whole point of a logo-only strip. Two sources are supported:

  * a PNG on disk -- Store apps ship one, and theirs is far crisper than
    anything extractable from the executable
  * an .exe/.dll/.ico -- the icon is pulled out at the largest size Windows
    will give us and cached as a PNG

Extraction shells out to PowerShell because it needs a P/Invoke into user32,
and pywin32 is not a dependency worth adding for one call that runs once per
icon and is then cached on disk.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .config import STATE_DIR

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ICON_CACHE = STATE_DIR / "icons"

# Windows will render an icon at any of these; we take the first that exists,
# so a modern app yields a 256px image and an old one still yields something.
SIZES = (256, 128, 96, 64, 48, 32)

EXTRACTABLE = {".exe", ".dll", ".ico", ".lnk"}

_EXTRACT_SCRIPT = r"""
param([string]$Source, [string]$Dest, [int[]]$Sizes)
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class PdIcon {
  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern int PrivateExtractIcons(string file, int index,
      int cx, int cy, IntPtr[] phicon, int[] piconid, int nIcons, int flags);
  [DllImport("user32.dll")]
  public static extern bool DestroyIcon(IntPtr hIcon);
}
"@
foreach ($size in $Sizes) {
  $handles = New-Object IntPtr[] 1
  $ids = New-Object int[] 1
  $count = [PdIcon]::PrivateExtractIcons($Source, 0, $size, $size, $handles, $ids, 1, 0)
  if ($count -gt 0 -and $handles[0] -ne [IntPtr]::Zero) {
    try {
      $icon = [System.Drawing.Icon]::FromHandle($handles[0])
      $bmp = $icon.ToBitmap()
      $bmp.Save($Dest, [System.Drawing.Imaging.ImageFormat]::Png)
      $bmp.Dispose()
      Write-Output $size
      exit 0
    } finally { [void][PdIcon]::DestroyIcon($handles[0]) }
  }
}
exit 1
"""


def _extract(source: Path, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    sizes = ",".join(str(s) for s in SIZES)
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command",
             f"& {{{_EXTRACT_SCRIPT}}} -Source '{source}' -Dest '{dest}' "
             f"-Sizes {sizes}"],
            capture_output=True, text=True, timeout=25, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and dest.exists()


# Resolved package install locations, keyed by package name. These change only
# when an app updates, and the lookup costs a PowerShell start-up.
_appx_cache: dict[str, str] = {}


def _appx_install_location(package_name: str) -> Path | None:
    """Find a Store app's install folder by package name.

    Needed because C:\\Program Files\\WindowsApps cannot be *enumerated*
    without elevation -- a wildcard there always comes back empty -- even
    though an exact file path inside it reads fine. Get-AppxPackage answers
    unelevated, so we ask it for the exact folder and build the path from that.
    """
    cached = _appx_cache.get(package_name)
    if cached and Path(cached).exists():
        return Path(cached)

    out = None
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-AppxPackage -Name '{package_name}' | "
             f"Select-Object -First 1).InstallLocation"],
            capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        if proc.returncode == 0:
            out = (proc.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return None

    if not out or not Path(out).exists():
        return None
    _appx_cache[package_name] = out
    return Path(out)


def source_for(slot: dict[str, Any]) -> Path | None:
    """Where this slot's icon should come from.

    An explicit ``icon_source`` wins; otherwise fall back to whatever the
    action launches, which is the executable in the common case.
    """
    explicit = slot.get("icon_source")
    if explicit:
        text = os.path.expandvars(str(explicit))

        # "appx:<PackageName>|<relative asset>" points inside a Store app,
        # whose folder name carries a version and so cannot be hard-coded.
        if text.lower().startswith("appx:"):
            body = text[5:]
            package, _, relative = body.partition("|")
            root = _appx_install_location(package.strip())
            if root is None:
                return None
            path = root / relative.strip().replace("\\", "/")
            return path if path.exists() else None

        path = Path(text)
        return path if path.exists() else None

    action = slot.get("action") or {}
    target = action.get("target")
    if not target:
        return None
    path = Path(os.path.expandvars(str(target)))
    return path if path.exists() else None


def icon_png(slot_id: str, slot: dict[str, Any]) -> Path | None:
    """A PNG on disk for this slot, extracting and caching if needed."""
    source = source_for(slot)
    if source is None:
        return None

    # A PNG source needs nothing done to it.
    if source.suffix.lower() == ".png":
        return source

    if source.suffix.lower() not in EXTRACTABLE:
        return None

    cached = ICON_CACHE / f"{slot_id}.png"
    try:
        fresh = cached.exists() and cached.stat().st_mtime >= source.stat().st_mtime
    except OSError:
        fresh = False
    if fresh:
        return cached

    return cached if _extract(source, cached) else None
