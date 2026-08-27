#!/usr/bin/env sh
# Serve. This is a shell with no schema/migrations yet — nothing to migrate or seed.
set -eu

echo "[boot] starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
