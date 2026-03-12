# Galactic AI — Self-Repair Restart Script
# Usage (from terminal): .\restart.ps1
#        (with optional port): .\restart.ps1 -Port 17789
#
# This script hits the /api/restart endpoint so a graceful restart
# is triggered the same way the UI "Restart" button works.
# The agent can invoke this via tool_run_command after making self-repairs.

param(
    [int]$Port = 17789
)

$url = "http://127.0.0.1:$Port/api/restart"
Write-Host "🔄 Sending restart signal to Galactic AI on port $Port..." -ForegroundColor Cyan

try {
    $response = Invoke-RestMethod -Uri $url -Method POST -ContentType "application/json" -Body '{"reason":"restart.ps1 invoked from terminal"}' -TimeoutSec 5
    if ($response.ok) {
        Write-Host "✅ Restart triggered: $($response.message)" -ForegroundColor Green
    } else {
        Write-Host "⚠️ Restart API returned: $response" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ Could not reach Galactic AI on port $Port. Is it running?" -ForegroundColor Red
    Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor DarkGray
    exit 1
}
