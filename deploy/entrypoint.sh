#!/usr/bin/env sh
# Optional boot steps, then serve.
#
# Both steps are OFF by default, so the production posture is unchanged: A6 deliberately kept
# `alembic upgrade head` a separate operator action, and that is still what happens unless
# MMOS_MIGRATE_ON_BOOT is explicitly set. A hosted demo has nobody at a terminal, so it turns
# these on via the environment.
set -eu

if [ "${MMOS_MIGRATE_ON_BOOT:-false}" = "true" ]; then
  echo "[boot] alembic upgrade head"
  python -m alembic upgrade head
fi

if [ "${MMOS_SEED_ON_BOOT:-false}" = "true" ]; then
  echo "[boot] seeding from the committed demo fixture (idempotent)"
  python -m app.seed --demo || echo "[boot] seed failed; starting the API anyway so the cause is visible in /healthz"
fi

echo "[boot] starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
