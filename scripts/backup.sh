#!/usr/bin/env bash
# Nightly backup of every MM OS Postgres database: dump, encrypt, retain, ship off-box.
#
# Meant to run on the VPS itself (cron, or a Coolify Scheduled Task), against the same
# Postgres the `postgres` compose service runs — either via `docker compose exec postgres
# pg_dump ...` or directly if pg_dump/openssl are installed on the host. This script talks
# to Postgres over TCP so it works either way; point PGHOST at whichever is reachable.
#
# Required env (set these in the environment the scheduler runs under, never hardcode a
# real value into this file):
#   BACKUP_PASSPHRASE     encrypts every dump with openssl. Losing this loses every backup.
#   POSTGRES_PASSWORD     same value as deploy/.env — the `mmos` role's password. As the
#                         bootstrap superuser it can pg_dump every database, not just its own.
#
# Optional env:
#   PGHOST                default: postgres     (the compose service name; use localhost
#                          if Postgres publishes a port on this host instead)
#   PGPORT                default: 5432
#   PGUSER                default: mmos
#   DATABASES             default: "mmos servicedesk itemcode att"
#   BACKUP_DIR            default: /var/backups/mmos   (local staging + retained copies)
#   RETENTION_DAYS        default: 14
#   OFFSITE_DEST          e.g. "user@remote-host:/backups/mmos/" for `rsync -e ssh`. If
#                          unset, backups stay local only — docs/06 requires off-VPS storage,
#                          so set this for a real deployment; documented as required in
#                          deploy/COOLIFY.md.
#
# Output: one file per database, $BACKUP_DIR/mmos_<db>_<UTC timestamp>.dump.enc
set -euo pipefail

: "${BACKUP_PASSPHRASE:?set BACKUP_PASSPHRASE — the passphrase every dump is encrypted with}"
: "${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD — same value as deploy/.env}"

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-mmos}"
DATABASES="${DATABASES:-mmos servicedesk itemcode att}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/mmos}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
OFFSITE_DEST="${OFFSITE_DEST:-}"

for bin in pg_dump openssl; do
    command -v "$bin" >/dev/null 2>&1 || { echo "error: $bin not found on PATH" >&2; exit 1; }
done

mkdir -p "$BACKUP_DIR"
export PGPASSWORD="$POSTGRES_PASSWORD"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FAILED=0

for db in $DATABASES; do
    plain="$BACKUP_DIR/mmos_${db}_${STAMP}.dump"
    enc="${plain}.enc"
    echo "[backup] dumping $db ..."
    if pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" -Fc -f "$plain"; then
        openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE \
            -in "$plain" -out "$enc"
        rm -f "$plain"
        chmod 600 "$enc"
        echo "[backup] $db -> $enc ($(du -h "$enc" | cut -f1))"
        if [ -n "$OFFSITE_DEST" ]; then
            if command -v rsync >/dev/null 2>&1; then
                rsync -az -e ssh "$enc" "$OFFSITE_DEST"
                echo "[backup] $db shipped to $OFFSITE_DEST"
            else
                echo "warning: rsync not found, $enc stayed local only" >&2
            fi
        else
            echo "warning: OFFSITE_DEST not set, $enc stayed local only — docs/06 requires off-VPS storage" >&2
        fi
    else
        echo "error: pg_dump failed for $db" >&2
        rm -f "$plain"
        FAILED=1
    fi
done

echo "[backup] applying retention: deleting files older than ${RETENTION_DAYS}d in $BACKUP_DIR"
find "$BACKUP_DIR" -maxdepth 1 -name 'mmos_*.dump.enc' -mtime "+${RETENTION_DAYS}" -print -delete

if [ "$FAILED" -ne 0 ]; then
    echo "[backup] completed with failures — see errors above" >&2
    exit 1
fi
echo "[backup] done."
