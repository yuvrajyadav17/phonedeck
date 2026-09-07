<#
    Flashes a Magisk-patched boot image to the Realme 1 (CPH1859).

    This is the point-of-no-return step of rooting. It is deliberately NOT
    run automatically -- it asks you to type YES before it touches the boot
    partition, because a wrong or mismatched image here bootloops the phone.

        powershell -ExecutionPolicy Bypass -File tools/flash_magisk.ps1 -Image "path\to\magisk_patched-XXXXX.img"

    Recovery if it does bootloop: the device is bootloader-unlocked, so you can
    always get back by flashing the STOCK boot.img the same way:
        fastboot flash boot stock_boot.img

    Device facts this script relies on (verified from your phone):
      * A-only layout  -> target partition is simply "boot"
      * musb-hdrc UDC, fastboot present at C:\platform-tools\fastboot.exe
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Image
)

$ErrorActionPreference = 'Stop'
$fastboot = 'C:\platform-tools\fastboot.exe'
$adb = 'adb'

if (-not (Test-Path $Image)) { throw "image not found: $Image" }
if (-not (Test-Path $fastboot)) { throw "fastboot not found at $fastboot" }

$size = [math]::Round((Get-Item $Image).Length / 1MB, 1)
Write-Host "Image to flash : $Image  ($size MB)" -ForegroundColor Cyan
Write-Host "SHA-256        : $((Get-FileHash $Image -Algorithm SHA256).Hash)"

# A patched Android 9 boot image is typically 16-32 MB. Flag anything wildly
# off, which usually means the wrong file was selected.
if ($size -lt 8 -or $size -gt 96) {
    Write-Host "WARNING: that size is unusual for a boot image. Double-check this is the Magisk-patched boot, not a full firmware or the wrong file." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Is the phone visible to adb right now?" -ForegroundColor Cyan
& $adb devices -l

Write-Host ""
Write-Host "This will reboot the phone into the bootloader and OVERWRITE its boot partition." -ForegroundColor Yellow
Write-Host "If the image is wrong the phone will bootloop (recoverable by flashing stock boot)." -ForegroundColor Yellow
$answer = Read-Host "Type exactly YES to proceed"
if ($answer -ne 'YES') { Write-Host "Aborted. Nothing was flashed." -ForegroundColor Green; exit 0 }

Write-Host "`n-> rebooting to bootloader..." -ForegroundColor Cyan
& $adb reboot bootloader

# Wait for the device to appear in fastboot rather than guessing a sleep.
Write-Host "-> waiting for fastboot..." -ForegroundColor Cyan
$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Seconds 2
    $devs = (& $fastboot devices) 2>$null
} until ($devs -or (Get-Date) -gt $deadline)

if (-not $devs) {
    throw "phone did not appear in fastboot within 60s. On the phone, the screen should say FASTBOOT. If not, hold Power+VolUp to reboot and try again."
}
Write-Host "   fastboot sees: $devs"

Write-Host "`n-> flashing boot..." -ForegroundColor Cyan
& $fastboot flash boot $Image
if ($LASTEXITCODE -ne 0) {
    Write-Host "flash FAILED. The phone is still in fastboot and unharmed. You can 'fastboot reboot' to return to the current system." -ForegroundColor Red
    throw "fastboot flash boot failed"
}

Write-Host "`n-> rebooting into the system..." -ForegroundColor Cyan
& $fastboot reboot

Write-Host ""
Write-Host "Done. When the phone boots, open the Magisk app -- if it shows 'Installed: 30.7', root is live." -ForegroundColor Green
Write-Host "Then tell me, and I'll build the HID unlock." -ForegroundColor Green
