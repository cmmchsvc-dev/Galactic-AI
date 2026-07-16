<#
.SYNOPSIS
    Galactic AI installer bootstrap (Windows).

.DESCRIPTION
    Makes sure Python and the VC++ runtime are present, then hands off to
    install.py, which does the real work (feature picking, Lite/Full/Custom,
    GPU detection, verification).

    All arguments are passed straight through to install.py.

.EXAMPLE
    .\install.ps1                      # guided install
    .\install.ps1 -profile lite        # fast, ~160 MB
    .\install.ps1 -profile full        # everything
    .\install.ps1 -list                # show features
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = 'Stop'
$ROOT = $PSScriptRoot

Write-Host ""
Write-Host "  Galactic AI - preparing installer..." -ForegroundColor Cyan
Write-Host ""

# ── 1. Visual C++ runtime (needed by several native wheels) ──────────────────
$vcKey = "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
if (-not (Test-Path $vcKey -ErrorAction SilentlyContinue)) {
    Write-Host "  [1/2] Installing Visual C++ Redistributable (one-time)..." -ForegroundColor Yellow
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $vc = "$env:TEMP\vc_redist.x64.exe"
        Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $vc
        Write-Host "        Approve the admin prompt to continue..." -ForegroundColor DarkYellow
        Start-Process -FilePath $vc -ArgumentList "/install /quiet /norestart" -Verb RunAs -Wait
        Write-Host "        Visual C++ installed." -ForegroundColor Green
    } catch {
        Write-Host "        Could not auto-install VC++. If you hit DLL errors later, get it from:" -ForegroundColor Yellow
        Write-Host "        https://aka.ms/vs/17/release/vc_redist.x64.exe" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "  [1/2] Visual C++ Redistributable: OK" -ForegroundColor Green
}

# ── 2. Python 3.9+ ───────────────────────────────────────────────────────────
function Get-PythonCmd {
    foreach ($c in @('python', 'python3', 'py')) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $v = & $c -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
                if ($v -and [version]$v -ge [version]'3.9') { return $c }
            } catch { }
        }
    }
    return $null
}

$py = Get-PythonCmd
if (-not $py) {
    Write-Host "  [2/2] Python 3.9+ not found. Installing Python 3.11..." -ForegroundColor Yellow
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $pyExe = "$env:TEMP\python-installer.exe"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $pyExe
        Start-Process -FilePath $pyExe -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [Environment]::GetEnvironmentVariable("Path", "User")
        $py = Get-PythonCmd
    } catch {
        Write-Host "  Python install failed: $_" -ForegroundColor Red
    }
    if (-not $py) {
        Write-Host ""
        Write-Host "  Please install Python 3.9+ manually, checking 'Add Python to PATH':" -ForegroundColor Red
        Write-Host "      https://www.python.org/downloads/" -ForegroundColor Cyan
        Write-Host "  Then re-run this installer." -ForegroundColor Red
        exit 1
    }
} else {
    $ver = & $py --version 2>&1
    Write-Host "  [2/2] $ver : OK" -ForegroundColor Green
}

& $py -m pip install --upgrade pip --quiet --disable-pip-version-check 2>$null

# ── 3. Hand off to the real installer ────────────────────────────────────────
Push-Location $ROOT
try {
    & $py "install.py" @Args
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
