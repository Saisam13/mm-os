#!/usr/bin/env bash
# scripts/verify/verify-security.sh -- mechanical security assertions (B3 hardening).
#
# Runs scripts/verify/_security_checks.py: admin-route 401/403, a placeholder pin_hash
# cannot authenticate, session cookie flags (HttpOnly/Secure/SameSite=Lax), the deny-list
# end to end (grant removal -> GET /api/agent/revocations, scoped per service), token
# verification (alg=none, RS256->HS256 confusion, wrong aud, revoked subject), and the
# X-Forwarded-For trust boundary. No Docker or Postgres needed -- runs against a scratch
# SQLite database, same as `acceptance.sh local`.
#
# Exit code is non-zero only if a mechanical assertion actually failed. WARN lines document
# known, already-written-up findings (see docs/11-security-review.md) -- they do not fail
# the run.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/backend/.venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then PY="$ROOT/backend/.venv/bin/python"; fi
if [ ! -x "$PY" ]; then PY="python"; fi

"$PY" "$ROOT/scripts/verify/_security_checks.py"
