$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Local-only convenience defaults. Set TDM_AUTH_MODE=production in your
# deployment environment and configure JWT settings for real authentication.
if (-not $env:TDM_AUTH_MODE) {
    $env:TDM_AUTH_MODE = "development"
}
if (-not $env:TDM_ALLOWED_ORIGINS) {
    $env:TDM_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,http://localhost:5500,http://127.0.0.1:5500"
}

Write-Host "Applying database migrations..."
python -m alembic upgrade head
Write-Host "Starting TDM Platform API at http://127.0.0.1:8000"
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
