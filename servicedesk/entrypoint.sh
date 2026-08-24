#!/usr/bin/env sh
# Migrate (and optionally seed), then serve. Both steps are opt-in via the environment.
set -eu

if [ "${SD_MIGRATE_ON_BOOT:-false}" = "true" ]; then
  echo "[boot] alembic upgrade head"
  python -m alembic upgrade head
fi

if [ "${SD_SEED_ON_BOOT:-false}" = "true" ]; then
  echo "[boot] seeding departments, SLA and approval routing (idempotent)"
  python -m app.seed || echo "[boot] seed reported a problem; starting anyway"
fi

echo "[boot] starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
