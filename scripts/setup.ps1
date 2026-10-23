<#
.SYNOPSIS
  One-time local setup for RABmate AI on Windows (PowerShell 5.1+).

.DESCRIPTION
  - Checks prerequisites (Python 3.12+, Node 24+, Docker Desktop running)
  - Creates .env from .env.example with freshly generated local secrets (never overwrites)
  - Creates the backend virtualenv and installs dependencies
  - Installs frontend dependencies from package-lock.json
  - Starts PostgreSQL (docker compose) and applies migrations

  Run from the repository root:
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root "services\api"
$Web = Join-Path $Root "apps\web"
$VenvPython = Join-Path $Api ".venv\Scripts\python.exe"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }
function Invoke-Checked {
  param([string]$File, [string[]]$Arguments)
  & $File @Arguments
  if ($LASTEXITCODE -ne 0) { Fail "$File $($Arguments -join ' ') (exit $LASTEXITCODE)" }
}

Step "Memeriksa prasyarat"
foreach ($cmd in "python", "node", "npm", "docker") {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Fail "$cmd tidak ditemukan di PATH." }
}
$pyVersion = (& python -c "import sys; print('%d.%d' % sys.version_info[:2])")
if ([version]$pyVersion -lt [version]"3.12") { Fail "Butuh Python >= 3.12 (terpasang $pyVersion)." }
$nodeMajor = [int]((& node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 24) { Fail "Butuh Node.js >= 24 (terpasang v$nodeMajor)." }
& docker info --format "{{.ServerVersion}}" *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker daemon tidak berjalan. Buka Docker Desktop lalu ulangi." }
Write-Host "Python $pyVersion, Node v$nodeMajor, Docker OK"

Step "Menyiapkan .env"
$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
  Write-Host ".env sudah ada - tidak diubah."
} else {
  $generator = @'
import pathlib, secrets, sys
root = pathlib.Path(sys.argv[1])
text = (root / ".env.example").read_text(encoding="utf-8")
text = text.replace("change-me-local-db-password", secrets.token_urlsafe(24))
text = text.replace("SECRET_KEY=change-me-in-.env", "SECRET_KEY=" + secrets.token_urlsafe(48))
(root / ".env").write_text(text, encoding="utf-8", newline="\n")
'@
  $generator | python - $Root
  if ($LASTEXITCODE -ne 0) { Fail "Gagal membuat .env" }
  Write-Host ".env dibuat dengan password database dan SECRET_KEY acak."
}

Step "Backend: virtualenv dan dependensi"
if (-not (Test-Path $VenvPython)) { Invoke-Checked python @("-m", "venv", (Join-Path $Api ".venv")) }
Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip", "--quiet")
Invoke-Checked $VenvPython @("-m", "pip", "install", "-e", "$Api[dev]", "--quiet")

Step "Frontend: npm ci"
Push-Location $Web
try { Invoke-Checked npm @("ci", "--no-fund") } finally { Pop-Location }

Step "PostgreSQL: docker compose up"
Push-Location $Root
try { Invoke-Checked docker @("compose", "up", "-d", "--wait", "db") } finally { Pop-Location }

Step "Migrasi database (alembic upgrade head)"
Push-Location $Api
try { Invoke-Checked $VenvPython @("-m", "alembic", "upgrade", "head") } finally { Pop-Location }

Write-Host "`nSetup selesai. Jalankan aplikasi dengan: powershell -ExecutionPolicy Bypass -File scripts\dev.ps1" -ForegroundColor Green
