# Thin host helper: ensure chimp is reachable, then open the status UI.
param(
    [string]$BaseUrl = "http://127.0.0.1:8787",
    [string]$Config = "config.yaml"
)

$ErrorActionPreference = "Stop"
$health = "$BaseUrl/health"
try {
    Invoke-RestMethod -Uri $health -TimeoutSec 2 | Out-Null
} catch {
    Write-Host "chimp not reachable at $health — starting..."
    if (-not (Test-Path $Config)) {
        throw "Missing $Config. Copy config.example.yaml first."
    }
    Start-Process -FilePath "chimp" -ArgumentList "--config", $Config -WindowStyle Minimized
    Start-Sleep -Seconds 2
}

Start-Process "$BaseUrl/ui"
