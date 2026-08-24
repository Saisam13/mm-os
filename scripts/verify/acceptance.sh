#!/usr/bin/env bash
# scripts/verify/acceptance.sh -- MM OS acceptance script (B1, run 2).
#
# Two modes, because this build machine genuinely cannot prove everything docs/08's v1
# definition of done asks for (no Docker, no Postgres -- docs/09's sprint amendments):
#
#   ./acceptance.sh local   (default) -- everything provable on a bare checkout with no
#                                        Docker and no Postgres: all four test suites, both
#                                        frontend builds, the real spreadsheet's dry-run
#                                        diff, and the token/deny-list checks.
#   ./acceptance.sh full    -- additionally the image build, `docker compose up`,
#                              `alembic upgrade head` against real Postgres, /healthz, and
#                              the JWKS check. Meant for a Docker host or the VPS.
#
# Every check prints exactly one PASS/FAIL/SKIP line. Nothing this script cannot actually
# prove is reported as passing -- an unmet precondition (no Docker, no Postgres, no
# reachable MM OS) is SKIP with the reason, never a silently-omitted line and never a PASS.
#
# See handoff/b1-assembly.md "Acceptance results" for the last verbatim run of this script.
#
# Extended by B3 (hardening, run 2) with three more local-mode checks: verify-security.sh
# (mechanical security assertions -- admin-route 401/403, a placeholder pin_hash cannot
# authenticate, session cookie flags, the deny-list end to end, token verification incl.
# alg=none/HS256 confusion, the X-Forwarded-For trust boundary), verify-offboard.sh
# (deactivating a user removes access from the shell session AND the service deny-list, in
# one process, synthetically), and verify-backup.sh (syntax + tool checks always; a real
# pg_dump/encrypt/restore/row-count round trip only if a real Postgres is reachable and
# POSTGRES_PASSWORD/BACKUP_PASSPHRASE are set -- SKIP otherwise, never a fabricated PASS).
# See docs/11-security-review.md and docs/10-runbook.md for what these checks are proving
# and what they still cannot prove without Docker or a live Postgres.

set -uo pipefail

MODE="${1:-local}"
case "$MODE" in
  local|full) ;;
  *) echo "usage: $0 [local|full]" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="$ROOT/backend/.venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then PY="$ROOT/backend/.venv/bin/python"; fi
if [ ! -x "$PY" ]; then PY="python"; fi

PASS=0
FAIL=0
SKIP=0
TMPOUT="$(mktemp)"
trap 'rm -f "$TMPOUT"' EXIT

pass() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL  %s -- %s\n' "$1" "$2"; }
skip() { SKIP=$((SKIP + 1)); printf 'SKIP  %s -- %s\n' "$1" "$2"; }

# run <label> <command...> -- PASS if the command exits 0, FAIL (with the last few lines of
# output) otherwise.
run() {
  local label="$1"; shift
  if "$@" >"$TMPOUT" 2>&1; then
    pass "$label"
  else
    fail "$label" "$(tail -5 "$TMPOUT" | tr '\n' ' ' | sed 's/  */ /g')"
  fi
}

# run_expect <label> <needle> <command...> -- PASS only if the command exits 0 AND its
# output contains <needle>. Use this where "exit 0" alone would not actually prove anything
# (e.g. a curl that succeeds against the wrong endpoint).
run_expect() {
  local label="$1" needle="$2"; shift 2
  if "$@" >"$TMPOUT" 2>&1 && grep -qF "$needle" "$TMPOUT"; then
    pass "$label"
  else
    fail "$label" "$(tail -5 "$TMPOUT" | tr '\n' ' ' | sed 's/  */ /g')"
  fi
}

have() { command -v "$1" >/dev/null 2>&1; }

echo "== MM OS acceptance -- mode: $MODE =="
echo

# ── local mode: everything provable with no Docker and no Postgres ──────────────────────
echo "-- local checks --"

run "backend/tests (60+ tests, 1 needs_postgres skip expected inside the suite)" \
  bash -c "cd '$ROOT/backend' && '$PY' -m pytest tests/ -q"

run "servicedesk/tests (31 tests)" \
  "$PY" -m pytest "$ROOT/servicedesk" -q

run "packages/mmos-client-py/tests (15 tests)" \
  "$PY" -m pytest "$ROOT/packages/mmos-client-py/tests" -q

if have node; then
  run "packages/embed/test/smoke.js (5 checks)" \
    node "$ROOT/packages/embed/test/smoke.js"
else
  skip "packages/embed/test/smoke.js" "node is not on PATH"
fi

# targeted re-statements of the two security-relevant behaviours named explicitly in the
# seam inventory, so they get their own line rather than hiding inside "backend/tests passed"
run "token mint + verify: RS256, JWKS, deny-list, alg-confusion (backend/tests/test_security.py)" \
  bash -c "cd '$ROOT/backend' && '$PY' -m pytest tests/test_security.py -q"
run "grant removal appears on GET /api/agent/revocations immediately (backend/tests/test_platform.py)" \
  bash -c "cd '$ROOT/backend' && '$PY' -m pytest tests/test_platform.py -k revocation -q"
run "client library rejects a revoked subject within one poll (packages/mmos-client-py)" \
  "$PY" -m pytest "$ROOT/packages/mmos-client-py/tests" -k revok -q
run "B1 seams: error envelope, public services, org-chain, admin shape drift (backend/tests/test_b1_seams.py)" \
  bash -c "cd '$ROOT/backend' && '$PY' -m pytest tests/test_b1_seams.py -q"

if have npm; then
  run "frontend: tsc --noEmit" \
    bash -c "cd '$ROOT/frontend' && npx tsc --noEmit"
  run "frontend: npm run build" \
    bash -c "cd '$ROOT/frontend' && npm run build"
  run "servicedesk/frontend: npm run build" \
    bash -c "cd '$ROOT/servicedesk/frontend' && npm run build"
else
  skip "frontend: tsc --noEmit" "npm is not on PATH"
  skip "frontend: npm run build" "npm is not on PATH"
  skip "servicedesk/frontend: npm run build" "npm is not on PATH"
fi

# the real spreadsheet's dry-run diff, against a scratch SQLite database (the same JSONB/UTC
# bridge backend/tests/conftest.py already applies) rather than the Postgres
# MMOS_DATABASE_URL normally points at -- see scripts/verify/_seed_dry_run.py.
SHEET_PATH="${MMOS_SHEET_PATH:-C:\Users\Anura\OneDrive\Desktop\Erp Imp\Employee_Role_Access_Mapping.xlsx}"
if [ -f "$SHEET_PATH" ]; then
  run_expect "seed dry-run against the real spreadsheet (73 employees, nothing written)" \
    "new:         73" \
    "$PY" "$ROOT/scripts/verify/_seed_dry_run.py" "$SHEET_PATH"
else
  skip "seed dry-run against the real spreadsheet" \
    "sheet not found at $SHEET_PATH (it lives outside the repo -- set MMOS_SHEET_PATH to point at it)"
fi

run "mechanical security assertions (verify-security.sh -- B3 hardening)" \
  bash "$ROOT/scripts/verify/verify-security.sh"

run "offboarding removes access everywhere, synthetic proof (verify-offboard.sh -- B3 hardening)" \
  bash "$ROOT/scripts/verify/verify-offboard.sh"

run "scripts/backup.sh + scripts/restore.sh: syntax and tool checks (verify-backup.sh -- B3 hardening)" \
  bash "$ROOT/scripts/verify/verify-backup.sh"

echo
echo "-- full-mode checks (Docker host / VPS only) --"

if [ "$MODE" != "full" ]; then
  skip "docker image build (deploy/Dockerfile)" "full mode not requested -- run '$0 full' on a Docker host"
  skip "docker compose up (deploy/docker-compose.yml)" "full mode not requested"
  skip "alembic upgrade head against real Postgres" "full mode not requested"
  skip "GET /healthz returns {\"ok\":true,\"db\":\"up\"}" "full mode not requested"
  skip "GET /.well-known/jwks.json returns an RSA key" "full mode not requested"
elif ! have docker; then
  skip "docker image build (deploy/Dockerfile)" "docker is not installed on this host (docs/09 sprint amendment: no Docker on the build machine)"
  skip "docker compose up (deploy/docker-compose.yml)" "docker is not installed on this host"
  skip "alembic upgrade head against real Postgres" "docker is not installed on this host"
  skip "GET /healthz returns {\"ok\":true,\"db\":\"up\"}" "docker is not installed on this host"
  skip "GET /.well-known/jwks.json returns an RSA key" "docker is not installed on this host"
else
  run "docker image build (deploy/Dockerfile)" \
    docker build -f "$ROOT/deploy/Dockerfile" -t mmos:acceptance "$ROOT"

  COMPOSE_UP_OK=0
  if docker compose -f "$ROOT/deploy/docker-compose.yml" up -d >"$TMPOUT" 2>&1; then
    pass "docker compose up (deploy/docker-compose.yml)"
    COMPOSE_UP_OK=1
  else
    fail "docker compose up (deploy/docker-compose.yml)" "$(tail -5 "$TMPOUT" | tr '\n' ' ')"
  fi

  if [ "$COMPOSE_UP_OK" = "1" ]; then
    # Give Postgres's healthcheck and the api container a moment to come up before probing.
    for _ in $(seq 1 30); do
      curl -sf http://localhost:8000/healthz >/dev/null 2>&1 && break
      sleep 2
    done

    run "alembic upgrade head against real Postgres" \
      docker compose -f "$ROOT/deploy/docker-compose.yml" exec -T api \
        python -m alembic upgrade head

    # Drift gate. The migration is hand-written (autogenerate needs a live DB, which the build
    # machine did not have), so nothing guaranteed it matched models.py until this ran: it
    # caught four indexes the migration created and the models never declared. Keep it.
    run "alembic check: models.py matches the migrated schema (drift gate)" \
      docker compose -f "$ROOT/deploy/docker-compose.yml" exec -T api \
        python -m alembic check

    run_expect 'GET /healthz returns {"ok":true,"db":"up"}' \
      '"db":"up"' \
      curl -sf http://localhost:8000/healthz

    run_expect "GET /.well-known/jwks.json returns an RSA key" \
      '"kty":"RSA"' \
      curl -sf http://localhost:8000/.well-known/jwks.json

    docker compose -f "$ROOT/deploy/docker-compose.yml" down >/dev/null 2>&1
  else
    skip "alembic upgrade head against real Postgres" "docker compose up failed, see above"
    skip "GET /healthz returns {\"ok\":true,\"db\":\"up\"}" "docker compose up failed, see above"
    skip "GET /.well-known/jwks.json returns an RSA key" "docker compose up failed, see above"
  fi
fi

echo
echo "== $PASS passed, $FAIL failed, $SKIP skipped =="
[ "$FAIL" -eq 0 ]
