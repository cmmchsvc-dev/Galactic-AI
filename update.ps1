# Galactic AI - Windows Auto-Updater
# Pulls the latest release directly from GitHub — no manual download needed.
#
# Usage (run from your Galactic AI installation folder):
#   .\update.ps1
#
# What is PRESERVED (never touched):
#   config.yaml         — all your API keys, passwords, Telegram settings
#   logs/               — chat history, memory cache, TTS files
#   workspace/          — your workspace files
#   watch/              — your watch folder
#   memory/             — your memory folder
#   MEMORY.md, USER.md, IDENTITY.md, SOUL.md, TOOLS.md
#
# What is UPDATED (safe to overwrite):
#   All .py source files, plugins, launch scripts, requirements.txt, docs

param(
    [string]$Version = "latest"   # Pin to a specific version e.g. "v0.7.1", or leave as "latest"
)

$GITHUB_REPO = "cmmchsvc-dev/Galactic-AI"
$GITHUB_API  = "https://api.github.com/repos/$GITHUB_REPO/releases"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  GALACTIC AI - Auto-Updater" -ForegroundColor Cyan
Write-Host "  Pulls latest release from GitHub" -ForegroundColor DarkCyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$InstallDir = $PSScriptRoot
if (-not $InstallDir) { $InstallDir = Get-Location }

# ── Step 1: Verify we're in a Galactic AI folder ──────────────────────────────
Write-Host "[1/6] Verifying installation..." -ForegroundColor Yellow
if (-not (Test-Path "$InstallDir\galactic_core_v2.py")) {
    Write-Host "  ERROR: galactic_core_v2.py not found." -ForegroundColor Red
    Write-Host "  Run this script from your Galactic AI installation folder." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path "$InstallDir\config.yaml")) {
    Write-Host "  ERROR: config.yaml not found. Use install.ps1 for fresh installs." -ForegroundColor Red
    exit 1
}

$currentVersion = "unknown"
$configContent = Get-Content "$InstallDir\config.yaml" -Raw
if ($configContent -match 'version:\s*([0-9.]+)') {
    $currentVersion = $Matches[1]
}
Write-Host "  Installed version : v$currentVersion" -ForegroundColor Green

# ── Step 2: Fetch latest release info from GitHub ─────────────────────────────
Write-Host "[2/6] Checking GitHub for updates..." -ForegroundColor Yellow

try {
    $headers = @{ "User-Agent" = "GalacticAI-Updater" }

    if ($Version -eq "latest") {
        $releaseInfo = Invoke-RestMethod -Uri "$GITHUB_API/latest" -Headers $headers
    } else {
        $releaseInfo = Invoke-RestMethod -Uri "$GITHUB_API/tags/$Version" -Headers $headers
    }
} catch {
    Write-Host "  ERROR: Could not reach GitHub API. Check your internet connection." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor DarkRed
    exit 1
}

$latestVersion = $releaseInfo.tag_name -replace '^v', ''
$latestTag     = $releaseInfo.tag_name

Write-Host "  Latest version    : $latestTag" -ForegroundColor Green

if ($latestVersion -eq $currentVersion) {
    Write-Host ""
    Write-Host "  You are already on the latest version (v$currentVersion)." -ForegroundColor Green
    Write-Host "  Use -Version to force a specific version: .\update.ps1 -Version v0.7.0" -ForegroundColor DarkGray
    Write-Host ""
    exit 0
}

Write-Host "  Update available  : v$currentVersion -> v$latestVersion" -ForegroundColor Cyan

# Find the windows ZIP asset
$asset = $releaseInfo.assets | Where-Object { $_.name -like "*windows*" -or $_.name -like "*Galactic-AI-v*.zip" } | Select-Object -First 1
if (-not $asset) {
    # Fall back to any ZIP
    $asset = $releaseInfo.assets | Where-Object { $_.name -like "*.zip" } | Select-Object -First 1
}
if (-not $asset) {
    Write-Host "  ERROR: No downloadable ZIP found in the GitHub release." -ForegroundColor Red
    Write-Host "  Visit: https://github.com/$GITHUB_REPO/releases" -ForegroundColor DarkCyan
    exit 1
}

$downloadUrl  = $asset.browser_download_url
$assetName    = $asset.name
Write-Host "  Downloading       : $assetName" -ForegroundColor DarkGray

# ── Step 3: Back up config.yaml ───────────────────────────────────────────────
Write-Host "[3/6] Backing up your configuration..." -ForegroundColor Yellow
$backupDir  = "$InstallDir\logs\backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$timestamp  = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = "$backupDir\config-backup-$timestamp.yaml"
Copy-Item "$InstallDir\config.yaml" $backupPath
Write-Host "  Backed up to: $backupPath" -ForegroundColor Green

# ── Step 4: Download the ZIP ──────────────────────────────────────────────────
Write-Host "[4/6] Downloading update..." -ForegroundColor Yellow
$tempZip = "$env:TEMP\galactic-update-$timestamp.zip"
try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $tempZip -UseBasicParsing
    $zipSizeMB = [math]::Round((Get-Item $tempZip).Length / 1MB, 1)
    Write-Host "  Downloaded $zipSizeMB MB." -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Download failed." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor DarkRed
    exit 1
}

# ── Step 5: Apply update (skip protected files) ───────────────────────────────
Write-Host "[5/6] Applying update..." -ForegroundColor Yellow

$protected = @("config.yaml", "logs", "workspace", "watch", "memory",
               "MEMORY.md", "USER.md", "IDENTITY.md", "SOUL.md", "TOOLS.md", "HEARTBEAT.md")

$tempDir = "$env:TEMP\galactic-update-extracted-$timestamp"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

try {
    Expand-Archive -Path $tempZip -DestinationPath $tempDir -Force

    # Handle both flat and nested ZIPs (Galactic-AI-vX.X.X/ subfolder)
    $innerDir = Get-ChildItem $tempDir -Directory | Select-Object -First 1
    $sourceDir = if ($innerDir) { $innerDir.FullName } else { $tempDir }

    $filesToCopy = Get-ChildItem $sourceDir -Recurse -File | Where-Object {
        $relPath  = $_.FullName.Substring($sourceDir.Length + 1)
        $topLevel = $relPath.Split([IO.Path]::DirectorySeparatorChar)[0]
        ($protected -notcontains $topLevel) -and ($protected -notcontains $relPath)
    }

    $copied = 0
    foreach ($file in $filesToCopy) {
        $relPath = $file.FullName.Substring($sourceDir.Length + 1)
        $dest    = Join-Path $InstallDir $relPath
        $destDir = Split-Path $dest -Parent
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        }
        Copy-Item $file.FullName $dest -Force
        $copied++
    }

    Write-Host "  Updated $copied files." -ForegroundColor Green
    Write-Host "  Protected (untouched): $($protected -join ', ')" -ForegroundColor DarkGray

} finally {
    Remove-Item -Recurse -Force $tempDir  -ErrorAction SilentlyContinue
    Remove-Item -Force        $tempZip   -ErrorAction SilentlyContinue
}

# ── Step 6: Update pip dependencies ───────────────────────────────────────────
Write-Host "[6/6] Updating Python dependencies..." -ForegroundColor Yellow
python -m pip install -r "$InstallDir\requirements.txt" --quiet --upgrade
Write-Host "  Dependencies up to date." -ForegroundColor Green

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Updated to $latestTag!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Your config, memory, and chat history are untouched." -ForegroundColor White
Write-Host "  Config backup: $backupPath" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "  Restart Galactic AI to apply:" -ForegroundColor White
Write-Host "    .\launch.ps1" -ForegroundColor Cyan
Write-Host ""
