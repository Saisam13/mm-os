#!/usr/bin/env bash
# scripts/verify/verify-backup.sh -- dump, restore into scratch, compare row counts (B3).
#
# docs/08-v1-plan.md's definition-of-done #8 ("a restore from backup has been performed
# into a scratch database and verified") needs a real Postgres server. There is none on
# this build machine (docs/09's standing amendment), so this script:
#
#   * ALWAYS runs the checks that need no database: `bash -n` on scripts/backup.sh and
#     scripts/restore.sh, and reports which of the required tools (pg_dump, pg_restore,
#     createdb, dropdb, psql, openssl) are on PATH.
#   * Attempts a REAL round trip -- pg_dump one database, encrypt, decrypt, pg_restore into
#     a scratch database, compare row counts on a couple of tables, drop the scratch
#     database -- ONLY if PGHOST is reachable and POSTGRES_PASSWORD/BACKUP_PASSPHRASE are
#     set. On this build machine that precondition is false, so those checks report SKIP
#     with the reason, never a fabricated PASS.
#
# Run this for real on the VPS (or any host with the real Postgres reachable):
#   PGHOST=<host> POSTGRES_PASSWORD=<real> BACKUP_PASSPHRASE=<real> \
#     scripts/verify/verify-backup.sh mmos
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB="${1:-mmos}"

PASS=0
FAIL=0
SKIP=0
pass() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL  %s -- %s\n' "$1" "$2"; }
skip() { SKIP=$((SKIP + 1)); printf 'SKIP  %s -- %s\n' "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "== MM OS backup/restore verification (target database: $DB) =="
echo

if bash -n "$ROOT/scripts/backup.sh"; then pass "scripts/backup.sh -- bash -n"; else fail "scripts/backup.sh -- bash -n" "syntax error"; fi
if bash -n "$ROOT/scripts/restore.sh"; then pass "scripts/restore.sh -- bash -n"; else fail "scripts/restore.sh -- bash -n" "syntax error"; fi

for bin in pg_dump pg_restore createdb dropdb psql openssl; do
  if have "$bin"; then
    pass "$bin is on PATH"
  else
    skip "$bin is on PATH" "not installed on this host"
  fi
done

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-mmos}"

if ! have pg_isready || ! have pg_dump || ! have pg_restore || ! have openssl; then
  skip "live dump -> encrypt -> restore -> row-count round trip" \
    "required Postgres client tools are not installed on this host (no Docker/Postgres on the build machine, per docs/09)"
elif [ -z "${POSTGRES_PASSWORD:-}" ] || [ -z "${BACKUP_PASSPHRASE:-}" ]; then
  skip "live dump -> encrypt -> restore -> row-count round trip" \
    "POSTGRES_PASSWORD / BACKUP_PASSPHRASE not set -- this is the guard against ever touching a real database by accident; set both and re-run on a host with Postgres reachable (see this script's header)"
elif ! PGPASSWORD="$POSTGRES_PASSWORD" pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" >/dev/null 2>&1; then
  skip "live dump -> encrypt -> restore -> row-count round trip" \
    "Postgres at $PGHOST:$PGPORT is not reachable from this host"
else
  export PGPASSWORD="$POSTGRES_PASSWORD"
  TMPDIR_BK="$(mktemp -d)"
  trap 'rm -rf "$TMPDIR_BK"' EXIT
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  PLAIN="$TMPDIR_BK/mmos_${DB}_${STAMP}.dump"
  ENC="${PLAIN}.enc"
  TARGET="${DB}_restore_verify_${STAMP}"

  ok=1
  if ! pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$DB" -Fc -f "$PLAIN"; then ok=0; fi
  if [ "$ok" = "1" ]; then
    openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -in "$PLAIN" -out "$ENC"
    openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$ENC" -out "${PLAIN}.roundtrip"
    if ! cmp -s "$PLAIN" "${PLAIN}.roundtrip"; then ok=0; fi
  fi
  if [ "$ok" = "1" ]; then pass "pg_dump -> openssl encrypt -> decrypt round trip is byte-identical"
  else fail "pg_dump -> openssl encrypt -> decrypt round trip is byte-identical" "dump or encrypt/decrypt step failed"; fi

  if [ "$ok" = "1" ] && createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$TARGET" 2>/dev/null; then
    if pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET" --clean --if-exists --no-owner "$PLAIN" 2>/dev/null; then
      pass "pg_restore into scratch database '$TARGET' succeeded"
      SRC_COUNTS="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$DB" -Atc \
        "SELECT coalesce((SELECT count(*) FROM employees),-1)" 2>/dev/null || echo -1)"
      DST_COUNTS="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET" -Atc \
        "SELECT coalesce((SELECT count(*) FROM employees),-1)" 2>/dev/null || echo -1)"
      if [ "$SRC_COUNTS" = "$DST_COUNTS" ] && [ "$SRC_COUNTS" != "-1" ]; then
        pass "row count on employees matches: source=$SRC_COUNTS restored=$DST_COUNTS"
      else
        fail "row count on employees matches" "source=$SRC_COUNTS restored=$DST_COUNTS"
      fi
    else
      fail "pg_restore into scratch database '$TARGET' succeeded" "pg_restore failed"
    fi
    dropdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$TARGET" 2>/dev/null || true
    echo "[verify-backup] dropped scratch database $TARGET"
  elif [ "$ok" = "1" ]; then
    fail "pg_restore into scratch database succeeded" "createdb failed"
  fi
fi

echo
echo "== $PASS passed, $FAIL failed, $SKIP skipped =="
[ "$FAIL" -eq 0 ]
