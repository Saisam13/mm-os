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
# Horizontal scaling is now SAFE (BE-6, L1/L2 phase). The rate limiters (POST /api/token/service,
# POST /api/auth/pin — 60/min each) used to be in-process, in-memory deques, which is why this was
# pinned to `--workers 1`: a second worker kept its own counters and every limit silently became N
# times more permissive. That state now lives in the shared `rate_limits` table in Postgres
# (app/ratelimit.py), so all workers/replicas share one budget. We leave uvicorn at its default
# (1 worker) here, but raising `--workers` or running multiple replicas is no longer forbidden.
# See docs/10-runbook.md §16.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
