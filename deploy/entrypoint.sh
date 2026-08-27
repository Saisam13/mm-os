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

echo "[boot] starting uvicorn (single worker — see below)"
# --workers 1 is REQUIRED, not incidental (BE-6). MM OS's rate limiters
# (POST /api/token/service, POST /api/auth/pin — 60/min each) and every mmos-client-py
# service's revocation deny-list are IN-PROCESS, IN-MEMORY state. With more than one worker
# each process keeps its own counters and its own deny-list, so every limit silently becomes
# N times more permissive and a revocation honored by one worker is ignored by the others —
# with no error and no test that would catch it. A single worker is a correct, deliberate
# posture for ~73 employees this phase; scaling past it needs a shared store (Redis) first.
# See docs/10-runbook.md §16 and docs/11-security-review.md finding #3. Do NOT raise this
# number without doing that work.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'
