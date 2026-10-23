<#
.SYNOPSIS
  Starts the local stack: PostgreSQL (Docker), FastAPI (port 8000), Next.js (port 3000).

.DESCRIPTION
  API and web run in their own PowerShell windows so their logs stay readable.
  Everything binds to 127.0.0.1 only. Close the windows to stop; stop the database with
    docker compose stop db

  Run from the repository root:
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root "services\api"
$Web = Join-Path $Root "apps\web"
$VenvPython = Join-Path $Api ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) { Write-Host "Jalankan scripts\setup.ps1 terlebih dahulu." -ForegroundColor Red; exit 1 }

Write-Host "==> PostgreSQL" -ForegroundColor Cyan
Push-Location $Root
try {
  & docker compose up -d --wait db
  if ($LASTEXITCODE -ne 0) { throw "docker compose gagal (apakah Docker Desktop berjalan?)" }
} finally { Pop-Location }

Write-Host "==> Migrasi" -ForegroundColor Cyan
Push-Location $Api
try {
  & $VenvPython -m alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw "alembic upgrade gagal" }
} finally { Pop-Location }

Write-Host "==> API  http://127.0.0.1:8000/api/v1/docs" -ForegroundColor Cyan
Start-Process powershell -WorkingDirectory $Api -ArgumentList @(
  "-NoExit", "-Command",
  "& '$VenvPython' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
)

Write-Host "==> Web  http://localhost:3000" -ForegroundColor Cyan
Start-Process powershell -WorkingDirectory $Web -ArgumentList @(
  "-NoExit", "-Command", "`$env:NEXT_TELEMETRY_DISABLED='1'; npm run dev"
)
