# Agent A6 · Infrastructure, deployment and runbooks

You are making **MM OS** deployable and operable. MM OS is the internal operating system for
MiniMines (~74 staff, lithium-ion battery recycling), running on a **Hostinger VPS managed by
Coolify**. It is **not internet-facing** — office LAN and WireGuard only. You are one of six
agents building in parallel, and yours is the branch that merges first, so everything you
produce must run against a repo where the other five branches do not exist yet.

**Read first:** `docs/06-network-security.md` (the posture you are implementing),
`docs/01-architecture.md` (deployment shape), `deploy/.env.example` (the env contract — it is
already written; extend it, do not restructure it).

## You own exclusively

```
deploy/**    scripts/**    .github/workflows/**
```

## Frozen — read, use, never edit

`backend/app/**`. In particular `config.py` defines the env contract (`MMOS_` prefix) and
`middleware.py` implements the CIDR gate. Your job is to make the environment match them, not
the reverse.

## Deliverables

1. **`deploy/Dockerfile`** — multi-stage: build the Vite frontend, then a slim Python 3.12
   image running uvicorn. One container, one port, FastAPI serving both API and the built
   bundle — the pattern `ATT_Platform` already uses here. Non-root user. Healthcheck hitting
   `/healthz`. Build must succeed when `frontend/` contains only a stub (A3 is still working),
   so guard the frontend stage.

2. **`deploy/docker-compose.yml`** — Postgres 16 with `pgcrypto`, the API, and a named volume.
   Postgres **must not publish a port to the host** — services reach it on the compose
   network. Signing key mounted as a file at `/run/secrets/mmos_signing_key.pem`.

3. **`scripts/gen-signing-key.sh`** — generate the RSA-2048 keypair, `chmod 600`, print the
   `kid` to put in the env. Refuse to overwrite an existing key without `--force`, because
   overwriting it invalidates every live token.

4. **`deploy/postgres/init.sql`** — one database and one role per service (`mmos`,
   `servicedesk`, `itemcode`, `att`), plus the **read-only role for the public surface of
   dual-mode services** exactly as in `docs/05-service-integration.md`. This read-only role is
   the structural protection that holds even when application routing is wrong, so get the
   `ALTER DEFAULT PRIVILEGES` line right.

5. **`deploy/COOLIFY.md`** — step-by-step for this VPS: create the app from the repo, env vars
   to set, the secret file mount, the healthcheck path, the domain, and how to deploy a second
   service (Service Desk) alongside. Written so someone who is not you can follow it at 11pm.

6. **`deploy/NETWORK.md`** — the runbook for the private posture:
   - `ufw` rules from `docs/06`
   - `wg-easy` as a Coolify container, one peer **per person** named by employee code, split
     tunnel `AllowedIPs=10.8.0.0/24`
   - **split-horizon DNS** so `os.m-mines.com` resolves internally to the private address
   - **TLS via DNS-01**, not HTTP-01 — HTTP-01 needs public port 80, which we no longer have.
     Give the concrete Caddy or Traefik DNS-01 configuration and the DNS provider API token
     setup.
   - the Google Cloud console redirect URI, and *why* Google OIDC still works when the host is
     private (the redirect happens in the browser; Google never resolves your host)
   - the monthly VPN-peer-versus-active-employees audit, as a checklist with a command

7. **`scripts/backup.sh` and `scripts/restore.sh`** — nightly `pg_dump` of every database,
   encrypted, written off the VPS, with retention. `restore.sh` must restore into a **scratch**
   database name by default, never over a live one. Document the quarterly restore test in
   `deploy/COOLIFY.md`. An untested backup is a rumour.

8. **`.github/workflows/ci.yml`** — lint, then pytest against a Postgres service container,
   then build the Docker image. It must pass on the current repo where most routers are
   stubs, and keep passing as agents land — so no test-count thresholds and no coverage gates.

9. **`scripts/dev.sh` / `scripts/dev.ps1`** — one command to bring up Postgres, run
   migrations, seed, and start the API with reload. Windows PowerShell **and** bash, because
   the developer machine is Windows 11 and the server is Linux.

## Rules that matter

- **Secrets are mounted files, not env vars,** for the signing key. Env vars leak into logs,
  crash reports and `docker inspect`.
- `MMOS_TRUSTED_PROXY_COUNT` must match the real proxy depth in front of the app. Get this
  wrong and either every client IP reads as the proxy (allowlist blocks everyone) or a caller
  can spoof one (allowlist becomes decoration). Document how to verify it with a real request.
- Nothing in `deploy/` may contain a real secret. `.env` is gitignored; `.env.example` carries
  placeholders only.
- Postgres is one instance with one database per service — isolated data, one engine to back
  up. Do not split it into per-service Postgres containers; the VPS cannot spare the RAM.

## Acceptance

- `docker compose -f deploy/docker-compose.yml up -d` on a clean machine gives a healthy `/healthz`
- `/.well-known/jwks.json` returns one RSA key generated by your script
- with `MMOS_NETWORK_MODE=private` and a CIDR list excluding the caller, every path except `/healthz` and the JWKS returns `403 network_denied`
- flipping to `public` reopens it with no code change
- `scripts/backup.sh` produces a file, and `restore.sh` restores it into a scratch database that a `psql` count confirms
- CI is green on the current repo

## Guardrails

Do not refactor `backend/` or add application code. No Kubernetes, no Terraform, no service
mesh — this is one VPS with Coolify. No new dependencies in `requirements.txt`. If a failure
resists two fixes, write it under `Not done`. Never put a real secret in a file, and never
touch the live ERPNext instance.

## Finish by writing `handoff/a6-infra.md`

`## Delivered`, `## Deviations`, `## Contract objections`, `## Assumptions`, `## Not done`,
`## How to verify`.
