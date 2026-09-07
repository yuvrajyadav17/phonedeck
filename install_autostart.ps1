<#
    Installs PhoneDeck's Windows integration:

      * Startup    -> the background server, started at login (no console)
      * Start Menu -> "PhoneDeck Editor", the standalone editing window
      * Desktop    -> the same editor shortcut, for double-clicking

        powershell -ExecutionPolicy Bypass -File install_autostart.ps1
        powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove
        powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -NoDesktop

    Shortcuts in the per-user Startup and Start Menu folders are used rather
    than a scheduled task or an installer: no administrator rights, visible in
    Task Manager's Startup tab, and removable by deleting a file.

    pythonw.exe (not python.exe) is the target throughout, so nothing flashes a
    console window.
#>
param(
    [switch]$Remove,
    [switch]$NoDesktop
)

$ErrorActionPreference = 'Stop'

$root      = Split-Path -Parent $MyInvocation.MyCommand.Path
$icon      = Join-Path $root 'assets\phonedeck.ico'
$startup   = [Environment]::GetFolderPath('Startup')
$programs  = [Environment]::GetFolderPath('Programs')
$desktop   = [Environment]::GetFolderPath('Desktop')

$serverLink  = Join-Path $startup  'PhoneDeck.lnk'
$editorLink  = Join-Path $programs 'PhoneDeck Editor.lnk'
$desktopLink = Join-Path $desktop  'PhoneDeck Editor.lnk'

if ($Remove) {
    foreach ($link in @($serverLink, $editorLink, $desktopLink)) {
        if (Test-Path $link) { Remove-Item $link -Force; Write-Host "Removed $link" -ForegroundColor Green }
    }
    Write-Host "PhoneDeck will no longer start at login." -ForegroundColor Cyan
    Write-Host "The server may still be running; quit it from the tray icon."
    return
}

# Prefer pythonw.exe from the same installation as the python.exe on PATH.
$python  = (Get-Command python -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Host "pythonw.exe not found next to $python; using python.exe" -ForegroundColor Yellow
    $pythonw = $python
}

$shell = New-Object -ComObject WScript.Shell

function New-Link($path, $script, $description) {
    $sc = $shell.CreateShortcut($path)
    $sc.TargetPath       = $pythonw
    $sc.Arguments        = $script
    $sc.WorkingDirectory = $root
    $sc.WindowStyle      = 7            # minimised, never steals focus
    $sc.Description      = $description
    if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
    $sc.Save()
    Write-Host "Installed $path" -ForegroundColor Green
}

New-Link $serverLink 'run.py' 'PhoneDeck - phone dashboard and shortcut server'
New-Link $editorLink 'editor_app.py' 'PhoneDeck Editor - edit shortcuts and top-bar slots'
if (-not $NoDesktop) { New-Link $desktopLink 'editor_app.py' 'PhoneDeck Editor' }

Write-Host ""
Write-Host "The server starts at your next login and sits in the system tray." -ForegroundColor Cyan
Write-Host "Open the editor from the tray icon, the Start Menu, or the desktop."
Write-Host ""
Write-Host "To undo:" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove"
