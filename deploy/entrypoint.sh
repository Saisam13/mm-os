#!/usr/bin/env sh
# Boot sequence for the hosted demo: migrate, seed, then serve.
#
# The production Dockerfile deliberately does NOT do this — A6 kept migrations a separate,
# deliberate operator step, which is right for production. A hosted demo has nobody at a
# terminal to run `alembic upgrade head`, so this entrypoint exists for deploy/docker-compose
# .coolify.yml only, and is selected there by overriding `command:`.
set -eu

echo "[boot] alembic upgrade head"
python -m alembic upgrade head

if [ "${MMOS_SEED_ON_BOOT:-false}" = "true" ]; then
  echo "[boot] seeding (idempotent)"
  python -m app.seed || echo "[boot] seed reported a problem; continuing so the API still starts"
fi

echo "[boot] starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
