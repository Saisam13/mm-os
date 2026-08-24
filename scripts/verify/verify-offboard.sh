#!/usr/bin/env bash
# scripts/verify/verify-offboard.sh -- prove access is gone everywhere (B3 hardening).
#
# Two uses:
#
#   scripts/verify/verify-offboard.sh
#       Synthetic proof against a scratch SQLite database: deactivates a throwaway user
#       through the real PATCH /api/admin/users/{id} route and proves the shell session,
#       every existing cookie value, and the service deny-list all agree access is gone --
#       in one process, no live MM OS needed. This is what CI / `acceptance.sh` runs.
#
#   scripts/verify/verify-offboard.sh --code MM19 --database-url "$MMOS_DATABASE_URL"
#       Read-only check against a REAL MM OS database, after actually offboarding someone
#       for real (see docs/10-runbook.md "Offboard an employee"). Confirms: the user is
#       inactive, has no live sessions, and has an unexpired global revocation row. Writes
#       nothing.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/backend/.venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then PY="$ROOT/backend/.venv/bin/python"; fi
if [ ! -x "$PY" ]; then PY="python"; fi

"$PY" "$ROOT/scripts/verify/_offboard_check.py" "$@"
