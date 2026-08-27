# Password Manager

Deployable **shell** for a future internal password manager. Own FastAPI service, own
container — not part of the MM OS codebase, same pattern as `servicedesk/`.

> ## The one invariant this product exists to keep
> **Every person's passwords are theirs alone. No one else can ever see them — not IT, not a
> platform admin, not the MM OS shell, not whoever operates the server, not whoever
> compromises it.** This is a zero-knowledge guarantee enforced by cryptography, not a
> policy or a permission setting that an admin could flip. MM OS proves *who you are*; it is
> never given the ability to *read what you store*. If any future change would let an
> operator or admin read a user's secrets, that change is wrong by definition — see
> `SECURITY.md`.

**This is not a password manager yet.** It authenticates via MM OS and shows a placeholder
page. It stores no secrets, has no vault, no encryption, and no autofill. Read
`SECURITY.md` before adding any of that.

## What exists

- MM OS auth seam (`app/mmos_seam.py`), copied faithfully from `servicedesk/app/mmos_seam.py`:
  offline RS256/JWKS verification + deny-list in `AUTH_MODE=http` (production), a local stub
  token codec in `AUTH_MODE=stub` (dev/tests only).
- `GET /healthz` — liveness + DB connectivity.
- `GET /api/me` — the one placeholder authenticated route: returns the caller's identity
  from their MM OS token, plus a `vault: {status: "not_implemented"}` marker.
- `GET /` — minimal server-rendered page: "Password Manager — signed in as {name}. Your
  vault will live here." (or a sign-in prompt if there's no valid token).
- `POST /_dev/token`, `POST /_mmos/accept`, `GET /_mmos/health` — the same stub-mode MM OS
  integration surface servicedesk exposes, gated to `AUTH_MODE=stub` only.
- Fail-closed boot guard: refuses to start if `ENVIRONMENT=production` and `AUTH_MODE` is
  still `stub` (see `app/main.py`).

## Run

```bash
cd passwordmanager
../backend/.venv/Scripts/python.exe -m pip install -r requirements.txt   # first time only
../backend/.venv/Scripts/python.exe -m uvicorn app.main:app --port 8020 --app-dir .
```

Frontend, in a second shell (dev server with API proxy — see `frontend/vite.config.js`):

```bash
cd passwordmanager/frontend
npm install
npm run dev
```

`npm run build` in `frontend/` produces `frontend/dist`, which the Dockerfile bakes into the
image; `app/main.py` currently mounts it at `/static` only (the placeholder page itself is
server-rendered at `/`, not the built SPA — see `app/main.py`'s comments for why both exist).

## Tests

```bash
cd passwordmanager
../backend/.venv/Scripts/python.exe -m pytest -q
```

All on SQLite, no Docker, no live network — `tests/conftest.py` is this service's own
harness. `tests/test_boot_guard.py` exercises the production fail-closed guard in a
subprocess (it's an import-time check).

## Environment variables

See `.env.example`. Key ones:

- `AUTH_MODE` — `stub` (dev/test) or `http` (production; requires `MMOS_SERVICE_KEY`).
- `ENVIRONMENT` — set to `production` on a real deployment; combined with `AUTH_MODE=stub`
  this refuses to boot (see above).
- `MMOS_SERVICE_SLUG` — `passwordmanager`. Determines the session cookie name
  (`passwordmanager_mmos_at`) and the `{slug}` in MM OS's launch URL.
- `DEV_SECRET` — HMAC key for the stub token codec. Dev/test only, never used in `http` mode.

## Registering this service in MM OS (not done by this agent)

This shell does not touch MM OS's seed data or spine. To actually launch it from MM OS:

1. Register a service record with `slug=passwordmanager`, its base URL (e.g.
   `https://passwordmanager.m-mines.com` or wherever it's deployed), and a service key —
   same shape as servicedesk's registration, see `docs/05-service-integration.md`.
2. Add a launch tile in MM OS's app catalog pointing at that base URL.
3. Set this service's `AUTH_MODE=http` and `MMOS_SERVICE_KEY` to the issued key before
   putting it anywhere near production traffic — see the fail-closed guard above.

## Slug and launch URL

- `slug`: `passwordmanager`
- Cookie: `passwordmanager_mmos_at`
- Local dev URL: `http://localhost:8020`
