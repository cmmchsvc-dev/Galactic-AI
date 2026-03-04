# Galactic AI - Ignition Script
Clear-Host
# Force UTF-8 so Unicode splash art renders correctly on all Windows PCs
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Host.UI.RawUI.WindowTitle = "GALACTIC AI DASHBOARD"
python splash.py
python -u galactic_core_v2.py
