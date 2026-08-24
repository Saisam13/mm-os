# echo-service

The ~100-line FastAPI service that proves `mmos-client-py` implements the contract in
`docs/05-service-integration.md`. Nothing else needs to be running — it spins up a stub of
MM OS's public surface (JWKS, revocations, heartbeat) in a background thread on startup.

## Run it — one command

```
backend/.venv/Scripts/python.exe examples/echo-service/main.py
```

Starts the echo service on `http://127.0.0.1:8090` and the stub MM OS on
`http://127.0.0.1:8199` (override with `PORT` / `STUB_MMOS_PORT`).

## Try it with curl

```bash
# 1. mint a token from the embedded stub (a real service never has a route like this —
#    a real token comes from MM OS's POST /api/token/service)
TOKEN=$(curl -s "http://127.0.0.1:8090/_demo/mint?roles=viewer" | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl http://127.0.0.1:8090/api/public/ping                                    # public, no token
curl http://127.0.0.1:8090/api/whoami -H "Authorization: Bearer $TOKEN"       # echoes your claims
curl -X POST http://127.0.0.1:8090/api/admin/note \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"note":"hi"}'
# -> 403 {"error":"role_required","need":"admin","have":["viewer"]}

ADMIN=$(curl -s "http://127.0.0.1:8090/_demo/mint?roles=admin" | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -X POST http://127.0.0.1:8090/api/admin/note \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" -d '{"note":"hi"}'
# -> 200 {"ok":true,...}

curl -X POST http://127.0.0.1:8090/api/llm/echo \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"text":"hello"}'
```

## Prove the 60-second revocation SLA against the real background poller

```bash
TOKEN=$(curl -s "http://127.0.0.1:8090/_demo/mint?roles=viewer&sub=user:carol" | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8090/api/whoami -H "Authorization: Bearer $TOKEN"   # 200

curl -X POST "http://127.0.0.1:8199/_demo/revoke?sub=user:carol"   # simulates an admin removing the grant

sleep 60
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8090/api/whoami -H "Authorization: Bearer $TOKEN"   # 401 revoked
```

(`packages/mmos-client-py/tests/test_mmos_client.py::test_revocation_blocks_within_a_single_poll`
proves the same mechanism without the real 60-second wait.)

## Prove the LLM kill switch

```bash
curl -X POST "http://127.0.0.1:8199/_demo/llm?enabled=false"
# the echo service's cached flag only updates on its next heartbeat (every 5 minutes;
# packages/mmos-client-py/tests covers this deterministically via heartbeat.beat_once())
```

## What's real here vs. what's a demo shortcut

- `main.py` uses the real `mmos_client.MMOS` exactly as any other service would.
- `stub_mmos.py` and the `/_demo/*` routes exist only so this example needs nothing else
  running. A real MM OS-facing service has neither.
- `sys.path` is patched at the top of `main.py` to reach `packages/mmos-client-py` directly,
  since that package is deliberately not `pip install`-ed into the shared venv (see
  `handoff/a4-integration.md`). A real consumer would just `pip install mmos-client-py`.
