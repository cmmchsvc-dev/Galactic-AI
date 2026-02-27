# Galactic AI - Remove Autostart Task (ASCII-only)
# Run in PowerShell: .\remove_galactic_autostart.ps1

$ErrorActionPreference = 'Stop'
$taskName = 'GalacticAI_Orchestrator'

Write-Host '=== Galactic AI: Remove Autostart ==='

try {
  schtasks /Query /TN $taskName *> $null
  schtasks /Delete /TN $taskName /F | Out-Null
  Write-Host ('Removed scheduled task: ' + $taskName)
} catch {
  Write-Host ('No scheduled task found: ' + $taskName)
}

Write-Host 'Done.'
