# Galactic AI — Desktop Shortcut Creator
# Run this script once to create (or recreate) the Galactic AI desktop shortcut.
# The shortcut launches a PowerShell terminal running launch.ps1 with the custom icon.

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$LaunchFile = Join-Path $ScriptDir "launch.ps1"
$IconFile   = Join-Path $ScriptDir "galactic_ai_flux_v4.ico"
$Desktop    = [System.Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Galactic AI.lnk"

$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)

$shortcut.TargetPath      = "C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments       = "-NoProfile -ExecutionPolicy Bypass -File `"$LaunchFile`""
$shortcut.WorkingDirectory = $ScriptDir
$shortcut.IconLocation    = "$IconFile,0"
$shortcut.Description     = "Launch Galactic AI"
$shortcut.WindowStyle     = 1  # 1 = Normal window

$shortcut.Save()

Write-Host ""
Write-Host "✅ Shortcut created: $ShortcutPath" -ForegroundColor Cyan
Write-Host "   Target : $($shortcut.TargetPath)" -ForegroundColor DarkGray
Write-Host "   Args   : $($shortcut.Arguments)" -ForegroundColor DarkGray
Write-Host "   Icon   : $IconFile" -ForegroundColor DarkGray
Write-Host ""
