# Item Code Studio

A **shell**, not the product. This is a future MM OS service (item-code generation/registry)
that does not exist yet as an application — MM OS already shows a tile for it, pointing at a
placeholder URL. This directory makes that tile point at something real: a service that
boots, authenticates via MM OS's launch-token handoff, sets its own session, and shows a
signed-in placeholder page. Everything else (the actual item-code product) is future work.

Structure and auth seam mirror `servicedesk/` exactly — see that service's README and
`docs/05-service-integration.md` for the full contract this was built against.

## Run

```bash
cd itemcode
../backend/.venv/Scripts/python.exe -m pip install -r requirements.txt   # first time only
../backend/.venv/Scripts/python.exe -m uvicorn app.main:app --port 8020 --app-dir .
```

Frontend, in a second shell (dev server with API proxy — see `frontend/vite.config.js`):

```bash
cd itemcode/frontend
npm install
npm run dev
```

For production, `npm run build` in `frontend/` produces `frontend/dist`, which
`app/main.py` mounts and serves from the same port as the API.

## Auth (the whole point of this shell)

SSO is the launch-token handoff (`docs/04-auth-flow.md`): MM OS mints a short-lived,
single-audience RS256 token; this service verifies it **offline** via JWKS and the deny-list,
then sets its own session cookie (`itemcode_mmos_at`). It does not depend on a shared cookie
domain — services live on separate sslip.io IPs today, the OS domain comes later.

Two modes, switched by `AUTH_MODE` (see `app/mmos_seam.py`):

- `http` — production. Verifies real RS256 tokens against MM OS's published JWKS via
  `packages/mmos-client-py` (in this monorepo, imported directly — no vendoring needed).
- `stub` — local dev and every test in this repo. A lightweight HMAC-signed token, no live
  MM OS required.

**Fail closed**: `app/main.py` refuses to boot if `ENVIRONMENT=production` and
`AUTH_MODE != http` — absence of configuration must never mean open access. The only escape
hatch is an explicit, logged `ITEMCODE_ALLOW_STUB_IN_PROD=1`, which should never be set on a
real server.

### Manually verifying it (no live MM OS to sign in through)

```bash
curl -X POST http://localhost:8020/_dev/token -H 'Content-Type: application/json' \
     -d '{"name":"Dev User","roles":["viewer"]}'
```

Returns `{"token": "..."}` — use as `Authorization: Bearer <token>` against `/api/me`, or
open the frontend and use the "Sign in (dev)" screen (`frontend/src/DevSignIn.jsx`). This
endpoint 404s the instant `AUTH_MODE` is anything but `stub`.

## Env vars

| Var | Meaning | Default |
|---|---|---|
| `DATABASE_URL` | Own database — sqlite for dev/test, Postgres in production. Never MM OS's or another service's database. | `sqlite:///./itemcode.db` |
| `ENVIRONMENT` | `development` or `production` — gates the boot guard above. | `development` |
| `AUTH_MODE` | `stub` (dev/test) or `http` (production, real JWKS verification). | `stub` |
| `MMOS_SERVICE_KEY` | This service's key for calling back into MM OS (heartbeat, revocation poll) once wired to a live instance. | `""` |
| `MMOS_SERVICE_SLUG` | `itemcode` — also the cookie prefix (`itemcode_mmos_at`). | `itemcode` |
| `MMOS_OS_URL` / `MMOS_ISSUER` | MM OS's base URL / token issuer. | `https://os.m-mines.com` |
| `DEV_SECRET` | HMAC secret for stub-mode tokens. Dev/test only — irrelevant in `http` mode. | placeholder |

See `.env.example` for a ready-to-copy file.

## Tests

```bash
cd itemcode
../backend/.venv/Scripts/python.exe -m pytest -q
```

10 tests, all green: stub-mode sign-in (`/_dev/token` → `/api/me`), the missing/bad/revoked
token paths, the `/_mmos/health` and `/_mmos/accept` stub routes, and the production+stub
boot guard (run in a subprocess, since `Settings` is process-wide `lru_cache`d) — refuses to
boot, boots with the explicit override, and boots normally in development.

## What remains for the live phase (not done here)

1. **Registration in MM OS.** This agent did not edit MM OS's service registry/seed — that's
   the orchestrator's job. Registration details this service needs:
   - `slug`: `itemcode`
   - `launch URL`: wherever this container is deployed (e.g. an `https://<ip>.sslip.io:<port>`
     Coolify URL, matching the pattern the other services use) — replace the current
     placeholder tile URL with it.
   - a minted `MMOS_SERVICE_KEY` for this slug, set as this service's env var.
2. **Deploy.** Build the Docker image (`itemcode/Dockerfile`) and deploy it via Coolify on the
   Hostinger VPS, same as `servicedesk`. Set `AUTH_MODE=http`, `ENVIRONMENT=production`,
   `MMOS_SERVICE_KEY`, and a real `DATABASE_URL` (Postgres) at deploy time.
3. **The actual product.** Everything under item-code generation/registry — models, routes,
   frontend screens — is unbuilt. This shell only proves the auth seam and gives it a place
   to land (`app/routers/api.py`, currently just `/api/me`).
