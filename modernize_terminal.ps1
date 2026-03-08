# Galactic AI - Terminal Modernization Guide
# Use this to fix the "mangled text" and "no colors" issue on older Windows systems.

Write-Host "`n===============================================" -ForegroundColor Cyan
Write-Host "  MODERNIZING WINDOWS TERMINAL" -ForegroundColor Cyan
Write-Host "===============================================`n" -ForegroundColor DarkCyan

Write-Host "[1/2] Installing Windows Terminal (Modern ANSI support)..." -ForegroundColor Yellow
winget install Microsoft.WindowsTerminal
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Winget failed or not found. Please download manually: https://aka.ms/terminal" -ForegroundColor DarkRed
}

Write-Host "[2/2] Installing PowerShell 7 (Better Unicode handling)..." -ForegroundColor Yellow
winget install Microsoft.PowerShell
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Winget failed. Please download manually: https://aka.ms/powershell-release" -ForegroundColor DarkRed
}

Write-Host "`n" -ForegroundColor Gray
Write-Host "  To fix 'mojibake' forever, run this in an Admin PowerShell session:" -ForegroundColor Gray
Write-Host "  Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -Name 'SubmitControl' -Value 1 -Force" -ForegroundColor DarkGray
Write-Host "  (Or just use Windows Terminal; it handles UTF-8 automatically!)" -ForegroundColor Green

Write-Host "`nDONE! Restart the computer, then open 'Windows Terminal' to run Galactic AI.`n" -ForegroundColor Cyan
