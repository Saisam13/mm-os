#!/usr/bin/env sh
# Serve. No migration step yet -- there is no schema to migrate (this shell stores no
# secrets, see SECURITY.md); add one here if/when a real vault schema exists.
set -eu

echo "[boot] starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
