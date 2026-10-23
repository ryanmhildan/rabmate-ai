<#
.SYNOPSIS
  Runs every automated check: backend lint/format/types/tests and frontend lint/types/tests/build.

.PARAMETER NoDb
  Skip backend tests that need PostgreSQL (pytest -m "not db").

  Run from the repository root:
    powershell -ExecutionPolicy Bypass -File scripts\check.ps1 [-NoDb]
#>
param([switch]$NoDb)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root "services\api"
$Web = Join-Path $Root "apps\web"
$VenvPython = Join-Path $Api ".venv\Scripts\python.exe"
$failed = @()

function Run($name, $dir, [scriptblock]$block) {
  Write-Host "`n==> $name" -ForegroundColor Cyan
  Push-Location $dir
  try {
    & $block
    if ($LASTEXITCODE -ne 0) { $script:failed += $name }
  } finally { Pop-Location }
}

Run "backend: ruff check"   $Api { & $VenvPython -m ruff check . }
Run "backend: ruff format"  $Api { & $VenvPython -m ruff format --check . }
Run "backend: mypy"         $Api { & $VenvPython -m mypy app tests }
if ($NoDb) {
  Run "backend: pytest (tanpa DB)" $Api { & $VenvPython -m pytest -m "not db" }
} else {
  Run "backend: pytest"     $Api { & $VenvPython -m pytest }
}

$env:NEXT_TELEMETRY_DISABLED = "1"
Run "frontend: eslint"      $Web { npm run lint }
Run "frontend: typecheck"   $Web { npm run typecheck }
Run "frontend: vitest"      $Web { npm test }
Run "frontend: next build"  $Web { npm run build }

if ($failed.Count -gt 0) {
  Write-Host "`nGAGAL: $($failed -join ', ')" -ForegroundColor Red
  exit 1
}
Write-Host "`nSemua pemeriksaan lulus." -ForegroundColor Green
