# One command for local development on Windows.
#
# Brings up Postgres via deploy/docker-compose.yml, creates schema (Alembic if A1's
# migrations exist yet, otherwise the SQLAlchemy create_all fallback in app/db.py), seeds
# if backend/app/seed.py exists, then starts uvicorn with --reload.
#
# Requires: Docker Desktop (with the compose plugin) running, backend/.venv already
# created with backend/requirements.txt + backend/requirements-dev.txt installed. This
# machine (the one this script was written on) has neither  -  see handoff/a6-infra.md
# `## Not done`; this script is unexecuted, verify it on a machine that has Docker.
#
# Usage: powershell -File scripts/dev.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker not found. dev.ps1 needs Docker Desktop for Postgres  -  see deploy/docker-compose.yml."
    exit 1
}
try { docker compose version | Out-Null } catch {
    Write-Error "'docker compose' (the plugin) is required."
    exit 1
}

$VenvPy = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Error "backend\.venv not found. Create it first:`n  cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt"
    exit 1
}

$EnvFile = Join-Path $RepoRoot "deploy\.env"
$EnvExample = Join-Path $RepoRoot "deploy\.env.example"
if (-not (Test-Path $EnvFile)) {
    Write-Host "[dev] deploy\.env not found - copying deploy\.env.example (placeholders only, fine for local dev)"
    Copy-Item $EnvExample $EnvFile
}

$pgPasswordLine = (Get-Content $EnvFile | Where-Object { $_ -match '^POSTGRES_PASSWORD=' })
$pgPassword = ($pgPasswordLine -split '=', 2)[1]

# Local dev talks to Postgres on localhost, not the compose-internal 'postgres' hostname  - 
# only the containerized api service (deploy/docker-compose.yml) uses that hostname.
$env:MMOS_DATABASE_URL = "postgresql+psycopg://mmos:$pgPassword@localhost:5432/mmos"
if (-not $env:MMOS_SIGNING_KEY_PATH) {
    $env:MMOS_SIGNING_KEY_PATH = Join-Path $RepoRoot "deploy\secrets\mmos_signing_key.pem"
}
if (-not $env:MMOS_NETWORK_MODE) {
    $env:MMOS_NETWORK_MODE = "public"   # don't fight the allowlist on localhost during dev
}

Write-Host "[dev] starting Postgres (deploy/docker-compose.yml) ..."
docker compose -f deploy/docker-compose.yml up -d postgres

Write-Host "[dev] waiting for Postgres to report healthy ..."
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    $status = docker compose -f deploy/docker-compose.yml ps --format json postgres 2>$null |
        Select-String '"Health":"([a-z]+)"' | ForEach-Object { $_.Matches[0].Groups[1].Value }
    if ($status -eq "healthy") { $healthy = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $healthy) {
    Write-Error "Postgres did not become healthy in time"
    exit 1
}

Push-Location backend
try {
    if (Test-Path "alembic") {
        Write-Host "[dev] running Alembic migrations ..."
        & $VenvPy -m alembic upgrade head
    } else {
        Write-Host "[dev] backend\alembic not present yet - creating schema via app.db.init_db() instead"
        & $VenvPy -c "from app.db import init_db; init_db()"
    }

    if (Test-Path "app\seed.py") {
        Write-Host "[dev] seeding ..."
        & $VenvPy -m app.seed
    } else {
        Write-Host "[dev] backend\app\seed.py not present yet - skipping seed"
    }

    Write-Host "[dev] starting the API with reload on http://localhost:8000 ..."
    & $VenvPy -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
} finally {
    Pop-Location
}
