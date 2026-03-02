# Galactic AI - Standalone EXE Builder
# Uses PyInstaller to create a single-file executable.

Write-Host "--- Galactic AI Desktop Builder ---" -ForegroundColor Cyan

# 1. Ensure PyInstaller is available
if (-not (Get-Command "pyinstaller" -ErrorAction SilentlyContinue)) {
    Write-Host "Error: PyInstaller is not installed. Install it with 'pip install pyinstaller'." -ForegroundColor Red
    exit 1
}

# 2. Configure paths
$Icon = "galactic_ai_flux_v4.ico"
$MainScript = "launcher_desktop.py"
$AppName = "GalacticAI"

# 3. Build command
# --onefile: Bundles everything into a single .exe
# --windowed: Hides the console window on launch
# --icon: Sets the application icon
# --add-data: Includes non-python folders (skills, docs, chrome-extension)
# Note: Syntax for --add-data on Windows is "src;dst"

Write-Host "Starting build process (this may take a few minutes)..." -ForegroundColor Yellow

pyinstaller --onefile --console `
    --name $AppName `
    --icon $Icon `
    --add-data "skills;skills" `
    --add-data "docs;docs" `
    --add-data "chrome-extension;chrome-extension" `
    --add-data "config;config" `
    --add-data "personality.yaml;." `
    --add-data "CHANGELOG.md;." `
    --add-data "FEATURES.md;." `
    --add-data "README.md;." `
    --add-data "galactic_ai_flux_v4.ico;." `
    --clean `
    $MainScript

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nSuccessfully built GalacticAI.exe! Check the 'dist' directory." -ForegroundColor Green
}
else {
    Write-Host "`nBuild failed. Check the output above for errors." -ForegroundColor Red
}
