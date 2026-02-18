# Galactic AI - Windows Installer
# Run: .\install.ps1

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  GALACTIC AI - Automation Suite Installer" -ForegroundColor Cyan
Write-Host "  v0.6.0-Alpha" -ForegroundColor DarkCyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "[1/4] Checking Python..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Python not found. Install from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "  Make sure to check 'Add Python to PATH' during installation." -ForegroundColor Red
    exit 1
}
Write-Host "  Found: $pythonVersion" -ForegroundColor Green

# Install pip dependencies
Write-Host "[2/4] Installing Python dependencies..." -ForegroundColor Yellow
pip install aiohttp httpx pyyaml jinja2 beautifulsoup4 playwright
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: pip install failed." -ForegroundColor Red
    exit 1
}
Write-Host "  Dependencies installed." -ForegroundColor Green

# Install Playwright browser
Write-Host "[3/4] Installing Chromium browser engine..." -ForegroundColor Yellow
playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WARNING: Playwright browser install failed. Browser tools will not work." -ForegroundColor Yellow
} else {
    Write-Host "  Chromium installed." -ForegroundColor Green
}

# Create workspace directories
Write-Host "[4/4] Creating workspace directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "workspace" | Out-Null
New-Item -ItemType Directory -Force -Path "watch" | Out-Null
New-Item -ItemType Directory -Force -Path "memory" | Out-Null
Write-Host "  Directories created." -ForegroundColor Green

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  To start Galactic AI:" -ForegroundColor White
Write-Host "    .\launch.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Then open your browser to:" -ForegroundColor White
Write-Host "    http://127.0.0.1:17789" -ForegroundColor Cyan
Write-Host ""
Write-Host "  (Optional) For local AI with no API keys:" -ForegroundColor White
Write-Host "    1. Install Ollama: https://ollama.com/download" -ForegroundColor DarkCyan
Write-Host "    2. ollama pull qwen3:8b" -ForegroundColor DarkCyan
Write-Host ""
