# Galactic AI - Windows Installer
# Run: .\install.ps1

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  GALACTIC AI - Automation Suite Installer" -ForegroundColor Cyan
Write-Host "  v1.5.2" -ForegroundColor DarkCyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check VC++ Redistributable
Write-Host "[1/6] Checking Visual C++ Redistributable..." -ForegroundColor Yellow
$vcRegPath = "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
if (-not (Test-Path $vcRegPath -ErrorAction SilentlyContinue)) {
    Write-Host "  Missing VC++ Redist. Attempting automatic installation..." -ForegroundColor Yellow
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $vcUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    $vcInstaller = "$env:TEMP\vc_redist.x64.exe"
    Invoke-WebRequest -Uri $vcUrl -OutFile $vcInstaller
    Write-Host "  Please grant administrator permission in the pop-up to install Visual C++..." -ForegroundColor Yellow
    Start-Process -FilePath $vcInstaller -ArgumentList "/install /quiet /norestart" -Verb RunAs -Wait
    Write-Host "  VC++ Redistributable installed." -ForegroundColor Green
}
else {
    Write-Host "  VC++ Redistributable is already installed." -ForegroundColor Green
}

# Check Python
Write-Host "[2/6] Checking Python..." -ForegroundColor Yellow
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "  Python is not installed. Attempting automatic installation..." -ForegroundColor Yellow
    
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $pythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $installerPath = "$env:TEMP\python-installer.exe"
    
    Write-Host "  Downloading Python 3.11 (this may take a minute)..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $pythonUrl -OutFile $installerPath
    
    Write-Host "  Installing Python (this will run silently)..." -ForegroundColor Cyan
    Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
    
    Write-Host "  Reloading environment variables..." -ForegroundColor DarkCyan
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    
    if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
        Write-Host "  ERROR: Automatic Python install failed or PATH not updated." -ForegroundColor Red
        Write-Host "  Please install manually from https://www.python.org/downloads/" -ForegroundColor Red
        Write-Host "  Make sure to check 'Add Python to PATH' during installation, then run this installer again." -ForegroundColor Red
        exit 1
    }
}
$pythonVersion = python --version 2>&1
Write-Host "  Found: $pythonVersion" -ForegroundColor Green

# Upgrade pip
Write-Host "[3/6] Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
Write-Host "  pip upgraded." -ForegroundColor Green

# Install pip dependencies from requirements.txt
Write-Host "[4/6] Installing Python dependencies (this may take a few minutes)..." -ForegroundColor Yellow
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: pip install failed. Check internet connection and try again." -ForegroundColor Red
    exit 1
}
Write-Host "  Dependencies installed." -ForegroundColor Green

# Install Playwright browser
Write-Host "[5/6] Installing Chromium browser engine..." -ForegroundColor Yellow
playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WARNING: Playwright browser install failed. Browser tools will not work." -ForegroundColor Yellow
    Write-Host "  You can install manually later: playwright install chromium" -ForegroundColor DarkYellow
}
else {
    Write-Host "  Chromium installed." -ForegroundColor Green
}

# Create workspace directories
Write-Host "[6/6] Creating workspace directories..." -ForegroundColor Yellow
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
Write-Host "  The setup wizard will guide you through configuring" -ForegroundColor White
Write-Host "  API keys for 14+ AI providers." -ForegroundColor White
Write-Host ""
Write-Host "  (Optional) For local AI with no API keys:" -ForegroundColor White
Write-Host "    1. Install Ollama: https://ollama.com/download" -ForegroundColor DarkCyan
Write-Host "    2. ollama pull qwen3:8b" -ForegroundColor DarkCyan
Write-Host ""
