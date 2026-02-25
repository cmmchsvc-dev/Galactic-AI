<#
.SYNOPSIS
Builds a sanitized release ZIP of Galactic AI.

.DESCRIPTION
This script executes the Python release builder located in scripts/release.py.
It safely packages the application while scrubbing API keys from config.yaml
and removing personal workspace files (MEMORY.md, VAULT.md, etc.).
#>
param (
    [string]$Version = ""
)

Write-Host "Starting Galactic AI Release Builder..." -ForegroundColor Cyan

# Ensure Python is available
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Python is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

# Run the release script
if ($Version) {
    Write-Host "Syncing versions to $Version..." -ForegroundColor Yellow
    python .\scripts\release.py --set-version $Version
} else {
    python .\scripts\release.py
}

if ($LASTEXITCODE -eq 0) {
    Write-Host "Release build complete! Check the 'releases' directory." -ForegroundColor Green
} else {
    Write-Host "Release build failed. Check output above for details." -ForegroundColor Red
}
