# Deploying MM OS on Coolify (Hostinger VPS)

This is the step-by-step for the box, not a restatement of the design — that lives in
`docs/01-architecture.md` and `docs/06-network-security.md`. Read those first if something
here doesn't make sense; this file assumes you already know *why*, only *how*.

## 0 · Before you start

- The VPS already has Coolify installed and you can reach its dashboard.
- You have the repo pushed somewhere Coolify can pull from (its own git server, or GitHub —
  either works; Coolify polls or receives a webhook the same way).
- You are **not** exposing MM OS to the internet. Nothing in this guide opens port 80/443 to
  the public — see `deploy/NETWORK.md` for the firewall and WireGuard side of that.

## 1 · Create the application

1. Coolify dashboard → **New Resource → Docker Compose**.
2. Point it at the repo, branch `main`, compose file path `deploy/docker-compose.yml`.
3. Set the **build context to the repo root**, not `deploy/` — the Dockerfile copies
   `backend/`, `frontend/`, and `packages/embed/` as siblings, so the root has to be in the
   build context. Coolify's compose deployments already build relative to the repo root by
   default; just don't override it to `deploy/`.

## 2 · Environment variables

In the application's **Environment Variables** tab, paste the contents of
`deploy/.env.example` with every value filled in for real — do not upload the file itself,
Coolify stores these as its own encrypted env, which is the point. In particular:

| Variable | Set to |
|---|---|
| `MMOS_ISSUER` | `https://os.m-mines.com` |
| `POSTGRES_PASSWORD` | a generated secret — this becomes the `mmos` Postgres role's password |
| `MMOS_GOOGLE_CLIENT_ID` / `MMOS_GOOGLE_CLIENT_SECRET` | see §5, they do not exist yet |
| `MMOS_ALLOWED_CIDRS` | your actual office static IP(s) plus `10.8.0.0/24`, replacing the placeholder in `.env.example` |
| `MMOS_TRUSTED_PROXY_COUNT` | see §6 — do not guess this one |

Leave `MMOS_SIGNING_KEY_PATH` at the default (`/run/secrets/mmos_signing_key.pem`) — that is
the mount point set up in §3, not something you generate a value for here.

## 3 · The signing key secret file

The signing key is a mounted file, never an env var (env vars leak into logs, crash reports
and `docker inspect` — see `backend/app/config.py`'s own docstring on this). On the VPS,
outside Coolify's env system:

```bash
# on the VPS, in the repo checkout Coolify uses
scripts/gen-signing-key.sh deploy/secrets/mmos_signing_key.pem
```

This writes the PEM with `chmod 600` and prints a `kid` (e.g. `mmos-2026-08`) — put that
value into `MMOS_SIGNING_KEY_ID` in Coolify's env vars. `deploy/docker-compose.yml` already
mounts `deploy/secrets/mmos_signing_key.pem` into the `api` container at
`/run/secrets/mmos_signing_key.pem` via a compose `secrets:` block, so nothing about this
step is Coolify-specific — it is the same file compose expects locally.

**Never commit this file.** `*.pem` is already in `.gitignore`; verify Coolify's own storage
for the compose deployment isn't accidentally re-adding it (it deploys from the git checkout,
so an untracked file on the VPS never gets picked up by git, only by the compose mount).

Rotating the key: `scripts/gen-signing-key.sh` refuses to overwrite without `--force`, because
overwriting invalidates every live session and service token instantly. If you must rotate,
change `MMOS_SIGNING_KEY_ID` at the same time so old tokens's `kid` values are visibly stale
rather than silently mismatched, and expect every signed-in user to be asked to sign in again.

## 4 · Database bootstrap

`deploy/postgres/init.sql` runs automatically the first time the `postgres` volume is empty
(Postgres's own `docker-entrypoint-initdb.d` convention — it does **not** re-run on restart,
only on a fresh volume). Before first start:

1. Copy `deploy/postgres/init.sql` and replace every `CHANGE_ME_*` password with a real,
   distinct value **in the VPS checkout only** — never commit the filled-in version.
2. Keep a record (in your password manager, not in git) of which password belongs to which
   role — `servicedesk`, `itemcode`, `att`, `itemcode_public` — because those are what the
   *other* services (Service Desk, Item Code Studio, ATT), deployed as their own Coolify
   apps, will need in their own `DATABASE_URL`.

If you ever need to re-run it against an existing volume (e.g. adding a service database
later), run the relevant `CREATE ROLE` / `CREATE DATABASE` statements by hand with `psql`
inside the `postgres` container — `docker-entrypoint-initdb.d` scripts are first-boot only.

## 5 · Google OIDC credentials

`MMOS_GOOGLE_CLIENT_ID` / `MMOS_GOOGLE_CLIENT_SECRET` are empty in `.env.example` because
these do not exist yet. To create them:

1. Google Cloud Console → a project under the `m-mines.com` Workspace organisation →
   **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Web application**.
3. Authorised redirect URI: `https://os.m-mines.com/api/auth/google/callback` — this must be
   the exact string `backend/app/config.py`'s `redirect_uri` property produces
   (`issuer.rstrip("/") + google_redirect_path`); do not add or drop a trailing slash.
4. Under **OAuth consent screen**, restrict to internal / the `m-mines.com` domain so
   `MMOS_GOOGLE_HOSTED_DOMAIN` has something to actually restrict.
5. Paste the generated client ID and secret into Coolify's env vars for this app, redeploy.

See `docs/06-network-security.md`'s "Google OIDC wrinkle" section for *why* this still works
against a private host — the short version: the redirect happens in the requester's browser,
and Google never has to resolve `os.m-mines.com` itself.

## 6 · Verifying `MMOS_TRUSTED_PROXY_COUNT`

Coolify's own Traefik proxy sits in front of the `api` container, so there is exactly **one**
hop adding an `X-Forwarded-For` entry before your app sees the request — `MMOS_TRUSTED_PROXY_COUNT=1`
is correct for the default Coolify setup with nothing else in front of it. If you later put
Coolify itself behind another proxy or CDN, this number must go up by exactly that many hops,
or the allowlist either blocks everyone (set too high) or becomes spoofable (set too low) —
see `backend/app/deps.py:client_ip()` and `docs/06-network-security.md`.

To verify against a real request once deployed:

```bash
# from a machine OUTSIDE MMOS_ALLOWED_CIDRS, over the public internet
curl -s -H "X-Forwarded-For: 10.8.0.1" https://os.m-mines.com/api/me -o /dev/null -w '%{http_code}\n'
```

If this returns `403 network_denied`, the proxy count is deep enough that a spoofed header
alone can't get in — Traefik overwrites/appends its own entry, and your app is correctly
reading the hop *it* added, not the one the caller forged. If it returns anything else
(`401`, `200`, ...), `MMOS_TRUSTED_PROXY_COUNT` is trusting the client-supplied value and must
be increased. This could not be executed here — there is no deployed instance and no VPS
reachable from the build machine; run it once, after step 8.

## 7 · Deploying a second service alongside (Service Desk)

Service Desk is **its own repo, own container, own Postgres database** (`docs/07-service-desk.md`)
— it does not live in `deploy/docker-compose.yml` and this Dockerfile does not build it.
To add it as a sibling Coolify app on the same VPS:

1. **New Resource** in Coolify, pointed at the Service Desk repo, its own Dockerfile.
2. Give it `DATABASE_URL=postgresql://servicedesk:<password>@<mmos-postgres-container>:5432/servicedesk`
   — the same Postgres instance MM OS uses (§4), reached by Coolify's internal network. Find
   the exact internal hostname/network name Coolify assigned the `postgres` service from this
   compose stack in Coolify's resource view; it is not `postgres` from Service Desk's side
   unless Coolify put both stacks on the same Docker network — check this explicitly, it is
   the step most likely to be wrong at 11pm.
3. `MMOS_SERVICE_KEY` for Service Desk comes from `POST /api/admin/services` against the
   running MM OS instance (see `docs/05-service-integration.md` §"Registering a new service") —
   shown once, store it in Coolify's env for the Service Desk app, not in git.
4. Its own domain (`desk.m-mines.com`), same split-horizon DNS and DNS-01 TLS treatment as
   MM OS itself — see `deploy/NETWORK.md`.
5. Healthcheck path: `/_mmos/health` (the contract in `docs/05`, not `/healthz` — that path
   is MM OS's own convention, not every service's).

## 8 · Healthcheck and domain

- Healthcheck path in Coolify's app settings: `/healthz`. It answers `{"ok":true,"db":"up"}`
  even under `MMOS_NETWORK_MODE=private` — it's in `middleware.py`'s `ALWAYS_OPEN` list — so
  Coolify's own health probe (which does not originate from `MMOS_ALLOWED_CIDRS`) still works.
- Domain: `os.m-mines.com`, TLS via DNS-01 — see `deploy/NETWORK.md`, do not let Coolify
  default to HTTP-01, it will fail (no public port 80).

## 9 · Backups and the quarterly restore test

`scripts/backup.sh` is meant to run nightly via a Coolify **Scheduled Task** (or plain cron on
the VPS if you prefer not to route it through Coolify) — see the script's own header for the
exact invocation and required env vars (encryption passphrase, retention days, off-VPS
destination).

**Quarterly restore test** — put this in the actual calendar, not in someone's memory,
alongside the WireGuard peer audit in `deploy/NETWORK.md`:

1. Pick the most recent nightly backup file for `mmos`.
2. Run `scripts/restore.sh <backup-file>` with no `--force-live` flag — it restores into a
   scratch database (`<db>_restore_<timestamp>` by default) and never touches the live one.
3. `psql` into the scratch database, run a row count on a couple of tables you know should be
   non-empty (`employees`, `audit_log`), and compare against what you'd expect from the live
   system on that date.
4. Drop the scratch database once satisfied. If the restore failed or the counts don't add
   up, the backup is not a backup — fix it before the next quarter, not after the next
   incident.

## What could not be verified from the build machine

There is no Docker on this machine and no VPS reachable from it. Everything in this file that
says "deploy and check" has not been run — see `handoff/a6-infra.md` under `## Not done` for
the exact list and the commands to run them.
