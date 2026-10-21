$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path "node_modules\playwright-core")) {
  Write-Host "Installing playwright-core (browser download is not required)..."
  npm install --no-audit --no-fund
}

node debug/capture.mjs
exit $LASTEXITCODE
