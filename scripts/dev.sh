#!/usr/bin/env bash
# One command for local development on a machine that HAS Docker (unlike the machine this
# script was written on — see handoff/a6-infra.md `## Not done`, this file is unexecuted).
#
# Brings up Postgres via deploy/docker-compose.yml, creates schema (Alembic if A1's
# migrations exist yet, otherwise the SQLAlchemy create_all fallback in app/db.py), seeds
# if backend/app/seed.py exists, then starts uvicorn with --reload against a plain local
# Postgres connection (not the container-to-container URL compose's `api` service uses).
#
# Requires: docker (with the compose plugin), backend/.venv already created with
# backend/requirements.txt + backend/requirements-dev.txt installed.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."   # repo root, regardless of where this was invoked from

for bin in docker; do
    command -v "$bin" >/dev/null 2>&1 || {
        echo "error: $bin not found. dev.sh needs Docker for Postgres — see deploy/docker-compose.yml." >&2
        exit 1
    }
done
docker compose version >/dev/null 2>&1 || {
    echo "error: 'docker compose' (the plugin, not docker-compose v1) is required." >&2
    exit 1
}

VENV_PY="backend/.venv/Scripts/python.exe"
[ -x "$VENV_PY" ] || VENV_PY="backend/.venv/bin/python"   # Linux/macOS dev machines
[ -x "$VENV_PY" ] || {
    echo "error: backend/.venv not found. Create it first:" >&2
    echo "  cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt" >&2
    exit 1
}

if [ ! -f deploy/.env ]; then
    echo "[dev] deploy/.env not found — copying deploy/.env.example (placeholders only, fine for local dev)"
    cp deploy/.env.example deploy/.env
fi

# Local dev talks to Postgres on localhost, not the compose-internal 'postgres' hostname —
# only the containerized api service (deploy/docker-compose.yml) uses that hostname.
export MMOS_DATABASE_URL="postgresql+psycopg://mmos:$(grep -E '^POSTGRES_PASSWORD=' deploy/.env | cut -d= -f2-)@localhost:5432/mmos"
export MMOS_SIGNING_KEY_PATH="${MMOS_SIGNING_KEY_PATH:-$(pwd)/deploy/secrets/mmos_signing_key.pem}"
export MMOS_NETWORK_MODE="${MMOS_NETWORK_MODE:-public}"   # don't fight the allowlist on localhost during dev

echo "[dev] starting Postgres (deploy/docker-compose.yml) ..."
docker compose -f deploy/docker-compose.yml up -d postgres

echo "[dev] waiting for Postgres to report healthy ..."
for _ in $(seq 1 30); do
    status="$(docker compose -f deploy/docker-compose.yml ps --format json postgres 2>/dev/null | grep -o '"Health":"[a-z]*"' | cut -d'"' -f4 || true)"
    [ "$status" = "healthy" ] && break
    sleep 2
done
[ "$status" = "healthy" ] || { echo "error: Postgres did not become healthy in time" >&2; exit 1; }

if [ -d backend/alembic ]; then
    echo "[dev] running Alembic migrations ..."
    (cd backend && "../$VENV_PY" -m alembic upgrade head)
else
    echo "[dev] backend/alembic not present yet — creating schema via app.db.init_db() instead"
    (cd backend && "../$VENV_PY" -c "from app.db import init_db; init_db()")
fi

if [ -f backend/app/seed.py ]; then
    echo "[dev] seeding ..."
    (cd backend && "../$VENV_PY" -m app.seed)
else
    echo "[dev] backend/app/seed.py not present yet — skipping seed"
fi

echo "[dev] starting the API with reload on http://localhost:8000 ..."
(cd backend && "../$VENV_PY" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000)
