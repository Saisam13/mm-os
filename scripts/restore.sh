#!/usr/bin/env bash
# Restore a backup produced by scripts/backup.sh — into a SCRATCH database by default.
#
# Usage:
#   scripts/restore.sh <backup-file.dump.enc> [--db NAME] [--target NAME]
#   scripts/restore.sh <backup-file.dump.enc> --force-live      (see the warning below)
#
#   --db NAME       which original database this dump belongs to. Inferred from the
#                   filename (mmos_<db>_<timestamp>.dump.enc) when not given.
#   --target NAME   the database name to restore INTO. Default: <db>_restore_<UTC now>.
#   --force-live    restore into <db> itself, overwriting the live database. Requires
#                   RESTORE_CONFIRM=yes-overwrite-live in the environment as well — two
#                   independent things have to be true on purpose, because this is the one
#                   command in this repo that destroys production data if run carelessly.
#
# Required env: BACKUP_PASSPHRASE, POSTGRES_PASSWORD — same as scripts/backup.sh.
# Optional env: PGHOST (default postgres), PGPORT (default 5432), PGUSER (default mmos).
#
# An untested backup is a rumour — this is also the script for the quarterly restore test
# documented in deploy/COOLIFY.md: run it against last night's dump, count rows in the
# scratch database, then drop the scratch database.
set -euo pipefail

: "${BACKUP_PASSPHRASE:?set BACKUP_PASSPHRASE — must match what scripts/backup.sh used}"
: "${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD — same value as deploy/.env}"

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-mmos}"

FILE=""
DB=""
TARGET=""
FORCE_LIVE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --db)
            DB="${2:?--db requires a value}"; shift 2 ;;
        --target)
            TARGET="${2:?--target requires a value}"; shift 2 ;;
        --force-live)
            FORCE_LIVE=1; shift ;;
        -h|--help)
            sed -n '2,20p' "$0"; exit 0 ;;
        *)
            FILE="$1"; shift ;;
    esac
done

[ -n "$FILE" ] || { echo "usage: scripts/restore.sh <backup-file.dump.enc> [--db NAME] [--target NAME] [--force-live]" >&2; exit 1; }
[ -f "$FILE" ] || { echo "error: $FILE not found" >&2; exit 1; }

if [ -z "$DB" ]; then
    base="$(basename "$FILE")"
    # expects mmos_<db>_<timestamp>.dump.enc
    if [[ "$base" =~ ^mmos_([a-zA-Z0-9]+)_[0-9TZ]+\.dump\.enc$ ]]; then
        DB="${BASH_REMATCH[1]}"
    else
        echo "error: could not infer the source database from '$base' — pass --db NAME" >&2
        exit 1
    fi
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [ -z "$TARGET" ]; then
    TARGET="${DB}_restore_${STAMP}"
fi

if [ "$FORCE_LIVE" -eq 1 ]; then
    TARGET="$DB"
    if [ "${RESTORE_CONFIRM:-}" != "yes-overwrite-live" ]; then
        echo "error: --force-live also requires RESTORE_CONFIRM=yes-overwrite-live in the environment." >&2
        echo "This is deliberate friction: restore.sh's whole job is to never overwrite a live" >&2
        echo "database by accident, and --force-live alone is one flag away from a fat-fingered" >&2
        echo "production wipe. Set the env var too, in the same command, if you truly mean it." >&2
        exit 1
    fi
    echo "!! restoring OVER LIVE DATABASE '$DB' — this destroys its current contents !!" >&2
fi

for bin in pg_restore createdb openssl psql; do
    command -v "$bin" >/dev/null 2>&1 || { echo "error: $bin not found on PATH" >&2; exit 1; }
done

export PGPASSWORD="$POSTGRES_PASSWORD"
TMP_PLAIN="$(mktemp)"
trap 'rm -f "$TMP_PLAIN"' EXIT

echo "[restore] decrypting $FILE ..."
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$FILE" -out "$TMP_PLAIN"

if [ "$FORCE_LIVE" -ne 1 ]; then
    echo "[restore] creating scratch database '$TARGET' (owned by $PGUSER)"
    createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$TARGET"
fi

echo "[restore] restoring into '$TARGET' ..."
pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET" --clean --if-exists --no-owner "$TMP_PLAIN"

echo "[restore] done. Verify with, e.g.:"
echo "  psql -h $PGHOST -p $PGPORT -U $PGUSER -d $TARGET -c 'SELECT count(*) FROM employees;'"
if [ "$FORCE_LIVE" -ne 1 ]; then
    echo "[restore] this is a SCRATCH database — drop it when done verifying:"
    echo "  dropdb -h $PGHOST -p $PGPORT -U $PGUSER $TARGET"
fi
