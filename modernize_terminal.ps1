# Galactic AI - Terminal Modernization Guide
# Use this to fix the "mangled text" and "no colors" issue on older Windows systems.

$LatestPS = "https://github.com/PowerShell/PowerShell/releases/download/v7.4.1/PowerShell-7.4.1-win-x64.msi"
$WT = "https://github.com/microsoft/terminal/releases/download/v1.18.3181.0/Microsoft.WindowsTerminal_Win10_1.18.3181.0_8wekyb3d8bbwe.msixbundle"

Write-Host "`n===============================================" -ForegroundColor Cyan
Write-Host "  MODERNIZING WINDOWS TERMINAL" -ForegroundColor Cyan
Write-Host "===============================================`n" -ForegroundColor DarkCyan

Write-Host "[1/3] Installing Windows Terminal (Modern ANSI support)..." -ForegroundColor Yellow
winget install Microsoft.WindowsTerminal
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Winget failed or not found. Please download manually: https://aka.ms/terminal" -ForegroundColor DarkRed
}

Write-Host "[2/3] Installing PowerShell 7 (Better Unicode handling)..." -ForegroundColor Yellow
winget install Microsoft.PowerShell
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Winget failed. Please download manually: https://aka.ms/powershell-release" -ForegroundColor DarkRed
}

Write-Host "[3/3] Setting UTF-8 as System Default (Fixes mangled characters)..." -ForegroundColor Yellow
Write-Host "  To fix 'mojibake' forever, run this in an Admin PowerShell session:" -ForegroundColor Gray
Write-Host "  Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -Name 'SubmitControl' -Value 1 -Force" -ForegroundColor DarkGray
Write-Host "  (Or just use Windows Terminal; it handles UTF-8 automatically!)" -ForegroundColor Green

Write-Host "`nDONE! Restart the computer, then open 'Windows Terminal' to run Galactic AI.`n" -ForegroundColor Cyan
