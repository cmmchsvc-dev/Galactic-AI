# Galactic AI - Windows Updater
# Updates code files while preserving your config, keys, memory, and chat history.
# Run from your Galactic AI installation folder: .\update.ps1
#
# What is PRESERVED (never touched):
#   config.yaml         — all your API keys, passwords, Telegram settings
#   logs/               — chat history, memory cache, TTS files
#   workspace/          — your workspace files
#   watch/              — your watch folder
#   memory/             — your memory folder
#   ../*.md             — MEMORY.md, USER.md, IDENTITY.md, SOUL.md, TOOLS.md (one level up)
#
# What is UPDATED (safe to overwrite):
#   All .py source files, plugins, launch scripts, requirements.txt, docs

param(
    [string]$ZipPath = "",
    [string]$Version = "latest"
)

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  GALACTIC AI - Updater" -ForegroundColor Cyan
Write-Host "  Safely updates code, preserves your data" -ForegroundColor DarkCyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$InstallDir = $PSScriptRoot
if (-not $InstallDir) { $InstallDir = Get-Location }

# ── Step 1: Verify we're in a Galactic AI folder ──────────────────────────────
Write-Host "[1/5] Verifying installation..." -ForegroundColor Yellow
if (-not (Test-Path "$InstallDir\galactic_core_v2.py")) {
    Write-Host "  ERROR: galactic_core_v2.py not found." -ForegroundColor Red
    Write-Host "  Run this script from your Galactic AI installation folder." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path "$InstallDir\config.yaml")) {
    Write-Host "  ERROR: config.yaml not found. Is this a fresh install?" -ForegroundColor Red
    Write-Host "  Use install.ps1 for fresh installs, not the updater." -ForegroundColor Red
    exit 1
}
Write-Host "  Found Galactic AI installation at: $InstallDir" -ForegroundColor Green

# Read current version from config.yaml
$currentVersion = "unknown"
$configContent = Get-Content "$InstallDir\config.yaml" -Raw
if ($configContent -match 'version:\s*([0-9.]+)') {
    $currentVersion = $Matches[1]
}
Write-Host "  Current version: v$currentVersion" -ForegroundColor Green

# ── Step 2: Get the update ZIP ────────────────────────────────────────────────
Write-Host "[2/5] Locating update package..." -ForegroundColor Yellow

if ($ZipPath -eq "") {
    # Look for a ZIP in the current directory or parent directory
    $zips = @(Get-ChildItem -Path $InstallDir -Filter "Galactic-AI-v*.zip" -ErrorAction SilentlyContinue)
    $zips += @(Get-ChildItem -Path (Split-Path $InstallDir -Parent) -Filter "Galactic-AI-v*.zip" -ErrorAction SilentlyContinue)
    $zips += @(Get-ChildItem -Path "$env:USERPROFILE\Downloads" -Filter "Galactic-AI-v*.zip" -ErrorAction SilentlyContinue)

    if ($zips.Count -eq 0) {
        Write-Host "  No update ZIP found automatically." -ForegroundColor Yellow
        Write-Host "  Download the latest release ZIP and run:" -ForegroundColor White
        Write-Host "    .\update.ps1 -ZipPath 'C:\path\to\Galactic-AI-v0.7.1-windows.zip'" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  Or place the ZIP in your Downloads folder and run update.ps1 again." -ForegroundColor White
        exit 0
    }

    # Pick the newest one by name (version sort)
    $ZipPath = ($zips | Sort-Object Name | Select-Object -Last 1).FullName
}

if (-not (Test-Path $ZipPath)) {
    Write-Host "  ERROR: ZIP not found at: $ZipPath" -ForegroundColor Red
    exit 1
}

$zipName = Split-Path $ZipPath -Leaf
Write-Host "  Using: $zipName" -ForegroundColor Green

# ── Step 3: Back up config.yaml ───────────────────────────────────────────────
Write-Host "[3/5] Backing up your configuration..." -ForegroundColor Yellow
$backupDir = "$InstallDir\logs\backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = "$backupDir\config-backup-$timestamp.yaml"
Copy-Item "$InstallDir\config.yaml" $backupPath
Write-Host "  config.yaml backed up to: $backupPath" -ForegroundColor Green

# ── Step 4: Extract update (skipping protected files) ────────────────────────
Write-Host "[4/5] Applying update..." -ForegroundColor Yellow

# Files and folders to NEVER overwrite
$protected = @(
    "config.yaml",
    "logs",
    "workspace",
    "watch",
    "memory"
)

# Extract to a temp folder first
$tempDir = "$env:TEMP\galactic-update-$timestamp"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

try {
    Expand-Archive -Path $ZipPath -DestinationPath $tempDir -Force
    Write-Host "  Extracted ZIP to temp folder." -ForegroundColor DarkGray

    # Find the inner folder (Galactic-AI-vX.X.X/)
    $innerDir = Get-ChildItem $tempDir -Directory | Select-Object -First 1
    if (-not $innerDir) {
        Write-Host "  ERROR: Could not find folder inside ZIP." -ForegroundColor Red
        exit 1
    }
    $sourceDir = $innerDir.FullName

    # Count files to copy
    $filesToCopy = Get-ChildItem $sourceDir -Recurse -File | Where-Object {
        $relPath = $_.FullName.Substring($sourceDir.Length + 1)
        $topLevel = $relPath.Split([IO.Path]::DirectorySeparatorChar)[0]
        $protected -notcontains $topLevel -and $protected -notcontains $relPath
    }
    $copied = 0

    foreach ($file in $filesToCopy) {
        $relPath = $file.FullName.Substring($sourceDir.Length + 1)
        $dest = Join-Path $InstallDir $relPath
        $destDir = Split-Path $dest -Parent
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        }
        Copy-Item $file.FullName $dest -Force
        $copied++
    }

    Write-Host "  Updated $copied files." -ForegroundColor Green
    Write-Host "  Skipped protected files: $($protected -join ', ')" -ForegroundColor DarkGray

} finally {
    # Clean up temp dir
    Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
}

# ── Step 5: Update pip dependencies ───────────────────────────────────────────
Write-Host "[5/5] Updating Python dependencies..." -ForegroundColor Yellow
python -m pip install -r "$InstallDir\requirements.txt" --quiet --upgrade
Write-Host "  Dependencies up to date." -ForegroundColor Green

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Update complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Your config, memory, and chat history are untouched." -ForegroundColor White
Write-Host "  Config backup saved to: $backupPath" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "  Restart Galactic AI to apply the update:" -ForegroundColor White
Write-Host "    .\launch.ps1" -ForegroundColor Cyan
Write-Host ""
