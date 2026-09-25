#!/usr/bin/env sh
# Optional boot steps, then serve.
#
# Both migrate/seed steps are OFF by default, so the production posture is unchanged unless
# MMOS_MIGRATE_ON_BOOT / MMOS_SEED_ON_BOOT are set.
set -eu

# ── persisted-mount ownership fix ────────────────────────────────────────────
# A Coolify/Docker volume mounts root-owned regardless of the image dir's owner, so the
# non-root `mmos` user cannot write the persisted RSA signing key into /data
# (MMOS_SIGNING_KEY_PATH). We therefore start as root ONLY to chown the mounts, then
# re-exec this same script as `mmos` via gosu — so uvicorn and every boot step still run
# unprivileged. The second pass (already mmos) skips this block.
if [ "$(id -u)" = "0" ]; then
  chown -R mmos:mmos /data /run/secrets 2>/dev/null || true
  exec gosu mmos "$0" "$@"
fi

# Accept true / 1 / yes in any case, with stray quotes or spaces stripped: on 25 Sep the flag was
# set in Coolify and migrations still did not run, and the log said nothing about why.
migrate_flag=$(printf '%s' "${MMOS_MIGRATE_ON_BOOT:-}" | tr -d "\"' " | tr '[:upper:]' '[:lower:]')
case "$migrate_flag" in
  true|1|yes)
    echo "[boot] alembic upgrade head"
    python -m alembic upgrade head
    ;;
  *)
    echo "[boot] skipping migrations: MMOS_MIGRATE_ON_BOOT is '${MMOS_MIGRATE_ON_BOOT:-<unset>}' (set it to true)"
    ;;
esac

if [ "${MMOS_SEED_ON_BOOT:-false}" = "true" ]; then
  echo "[boot] seeding from the committed demo fixture (idempotent)"
  python -m app.seed --demo || echo "[boot] seed failed; starting the API anyway so the cause is visible in /healthz"
  echo "[boot] checking service URLs (repoint stale entries)"
  python /app/scripts/repoint_services.py --apply || echo "[boot] repoint check failed (non-fatal)"
fi

echo "[boot] starting uvicorn"
# Horizontal scaling is safe (BE-6): rate-limit state is shared in Postgres (app/ratelimit.py),
# not in-process, so raising --workers or running replicas is no longer forbidden. Default 1 worker.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
