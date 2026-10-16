$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "frontend-react")

if (-not (Test-Path (Join-Path $PWD "node_modules"))) {
    Write-Host "Installing frontend dependencies..."
    npm ci
}

Write-Host "Starting TDM Platform frontend at http://127.0.0.1:5173"
npm run dev -- --host 127.0.0.1
