<#
.SYNOPSIS
    Move the Galactic AI repo out of a Google Drive-synced folder.

.DESCRIPTION
    Google Drive Desktop is actively syncing this repo (see .tmp.driveupload/ and
    the "file (1).ext" conflict copies it leaves behind). Drive does not
    understand git: it can rewrite, duplicate, or partially upload files inside
    .git while git is mid-write, which corrupts the repository.

    This script COPIES the repo to a non-synced location and verifies the copy.
    It does NOT delete the original - you verify the new one works first, then
    remove the old copy yourself.

    Two phases:
      -Stage   Copy the durable data NOW, even while Galactic AI is running.
               Skips the live-locked memory store (logs/) so nothing is copied
               half-written. This de-risks the catastrophic case (a corrupted
               .git) immediately. Safe to run anytime.
      (default) The authoritative migration. Requires the app STOPPED so the
               memory store (logs/, chroma) copies cleanly. robocopy is
               incremental, so running this after a -Stage only tops up what
               changed - it re-uses the staged copy.

    Regenerable bloat is never copied (node_modules, __pycache__, *.pyc,
    releases/, Drive temp dirs). If you use GalacticIDE, run `npm install` in
    it once at the new location.

.NOTES
    Run from an ordinary PowerShell window. -Stage is fine anytime; the default
    full run needs Galactic AI fully STOPPED.

.EXAMPLE
    .\scripts\move_out_of_drive.ps1 -Stage
    .\scripts\move_out_of_drive.ps1
    .\scripts\move_out_of_drive.ps1 -Destination "D:\Dev\GalacticAI"
#>
[CmdletBinding()]
param(
    [string]$Source = (Split-Path -Parent $PSScriptRoot),
    [string]$Destination = "C:\Dev\GalacticAI",
    [switch]$Stage,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$mode = if ($Stage) { "STAGE (durable data, app may be running)" } else { "FULL migration (app must be stopped)" }
Write-Host "`n=== Galactic AI - move out of Google Drive sync ===" -ForegroundColor Cyan
Write-Host "Mode        : $mode" -ForegroundColor Cyan
Write-Host "Source      : $Source"
Write-Host "Destination : $Destination`n"

# 1. In FULL mode, refuse to run while the app is up (it holds the memory
#    store open - copying it live would produce an inconsistent DB).
$port = 17789
$live = $null
try { $live = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue } catch {}
if ($live -and -not $Stage -and -not $Force) {
    Write-Host "ABORT: Galactic AI is still running (port $port is listening)." -ForegroundColor Red
    Write-Host "For the FULL migration, shut it down first (Control Deck -> shutdown, or" -ForegroundColor Yellow
    Write-Host "close the console). Or run with -Stage now to copy everything except the" -ForegroundColor Yellow
    Write-Host "live memory store while it keeps running." -ForegroundColor Yellow
    exit 1
}

if ((Test-Path $Destination) -and -not $Stage) {
    $existing = Get-ChildItem -Force $Destination -ErrorAction SilentlyContinue
    if ($existing -and -not $Force) {
        Write-Host "NOTE: $Destination already exists (likely from a prior -Stage). robocopy" -ForegroundColor DarkGray
        Write-Host "      is incremental, so this will just update it. Continuing." -ForegroundColor DarkGray
    }
}

# 2. Snapshot git state so we can prove the copy is faithful.
Push-Location $Source
$srcHead = (git rev-parse HEAD 2>$null)
Pop-Location
Write-Host "Pre-copy git HEAD: $srcHead" -ForegroundColor DarkGray

# 3. Copy. /E all subdirs, /COPY:DAT + /DCOPY:DAT keep timestamps, /R:1 /W:1
#    never hang on a locked file, /NFL /NDL /NP quiet.
$excludeDirs = @('node_modules', '__pycache__', '.pytest_cache', 'releases',
                 '.tmp.driveupload', '.tmp.drivedownload')
if ($Stage) {
    # Live memory store + volatile logs: skip while the app is writing them.
    $excludeDirs += @('logs', 'chroma_data', 'chroma_data.bak')
}

$roboArgs = @($Source, $Destination, '/E', '/COPY:DAT', '/DCOPY:DAT',
              '/R:1', '/W:1', '/NFL', '/NDL', '/NP', '/XF', '*.pyc',
              '/XD') + $excludeDirs

Write-Host "`nCopying (this can take a few minutes)..." -ForegroundColor Cyan
robocopy @roboArgs | Out-Null
$rc = $LASTEXITCODE
# robocopy exit codes: 0-7 = success-ish, 8+ = real failure.
if ($rc -ge 8) {
    Write-Host "ABORT: robocopy failed with exit code $rc (locked/inaccessible files)." -ForegroundColor Red
    exit 1
}
Write-Host "Copy complete (robocopy code $rc = OK)." -ForegroundColor Green

# 4. Verify the copied repo's git integrity.
Write-Host "`nVerifying copied repository..." -ForegroundColor Cyan
Push-Location $Destination
$dstHead = (git rev-parse HEAD 2>$null)
git fsck --no-progress --no-dangling 2>&1 | Select-Object -First 10
$fsckOk = ($LASTEXITCODE -eq 0)
Pop-Location

Write-Host "`nSource HEAD      : $srcHead"
Write-Host "Destination HEAD : $dstHead"
if ($srcHead -ne $dstHead) {
    Write-Host "WARNING: HEAD mismatch - .git may have copied mid-write. Re-run the script." -ForegroundColor Red
} elseif (-not $fsckOk) {
    Write-Host "WARNING: git fsck found problems in the copy - re-run the script." -ForegroundColor Red
} else {
    Write-Host "Verified: HEAD matches and git fsck is CLEAN." -ForegroundColor Green
}

# 5. Confirm the irreplaceable untracked files made it (they are NOT in git).
$mustHave = @('.git', 'config.local.yaml', 'workspace', 'CHONG')
if (-not $Stage) { $mustHave += 'logs\galactic_memory.db' }
Write-Host "`nIrreplaceable files:" -ForegroundColor Cyan
foreach ($f in $mustHave) {
    $p = Join-Path $Destination $f
    if (Test-Path $p) { Write-Host "  OK      $f" -ForegroundColor Green }
    else              { Write-Host "  MISSING $f" -ForegroundColor Yellow }
}

if ($Stage) {
    Write-Host @"

=== STAGED. Your git history + code + config + memory MD + voice clips are now
    safely copied out of Google Drive. The live vector memory (logs/) was
    skipped because the app is using it. ===

To FINISH the migration later:
  1. Shut Galactic AI down completely.
  2. Re-run WITHOUT -Stage (it only tops up what changed):
         .\scripts\move_out_of_drive.ps1
  3. Follow the cutover steps it prints.
"@ -ForegroundColor Cyan
    exit 0
}

Write-Host @"

=== NEXT STEPS (do these yourself) ===

1. Start Galactic AI from the NEW location and confirm it works:
       cd "$Destination"
       python galactic_core_v2.py
   (If you use GalacticIDE: run 'npm install' inside GalacticIDE first -
    node_modules was intentionally not copied.)

2. Confirm the Control Deck loads at http://127.0.0.1:17789 and Chong replies,
   and that your memories/settings are intact.

3. Update any shortcuts that still point at the old path:
       - "Launch Galactic Desktop.vbs"
       - "Galactic AI Desktop.bat"  /  "Galactic CLI.bat"
       - Desktop / taskbar shortcuts
   (Search them for the old path string: $Source)

4. ONLY after all of the above works, remove the old copy from the synced
   folder:
       Remove-Item -Recurse -Force "$Source"

   Alternative: keep the folder where it is but open Google Drive Desktop ->
   Settings -> Preferences -> Folders from your computer, and STOP syncing this
   folder. That also removes the corruption risk without moving anything.
"@ -ForegroundColor Cyan
