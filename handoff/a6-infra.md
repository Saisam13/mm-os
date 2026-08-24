# A6 · Infrastructure, deployment and runbooks

## Delivered

- **`deploy/Dockerfile`** — two-stage build. Stage 1 (`node:20.18.1-bookworm-slim`) builds
  `frontend/dist`; guarded so it succeeds with only `frontend/README.md` present (A3 has not
  landed `package.json` yet — verified this is still the case as of writing). Stage 2
  (`python:3.12.7-slim-bookworm`) installs `backend/requirements.txt` verbatim, copies
  `backend/app`, `packages/embed`, and the built `frontend/dist`, runs as a non-root `mmos`
  user, `EXPOSE 8000`, a pure-Python `HEALTHCHECK` against `/healthz` (no curl added to the
  image for one GET), `CMD uvicorn app.main:app`. Must be built from the **repo root**
  (`docker build -f deploy/Dockerfile .`), not from `deploy/`.
- **`deploy/docker-compose.yml`** — `postgres:16.6-bookworm` (no host port published — the one
  hard requirement from the brief) plus `api` (built from the Dockerfile above), a named
  volume `mmos_pgdata`, and a compose `secrets:` block mounting
  `deploy/secrets/mmos_signing_key.pem` to exactly `/run/secrets/mmos_signing_key.pem` inside
  the container — the path `config.py` names, byte for byte.
- **`scripts/gen-signing-key.sh`** — `openssl genpkey` RSA-2048 PKCS#8, `chmod 600`, refuses to
  overwrite without `--force`, prints the `kid` to set as `MMOS_SIGNING_KEY_ID`.
- **`deploy/postgres/init.sql`** — creates `servicedesk`, `itemcode`, `att` databases/roles
  (`mmos` itself is created by the Postgres image's own bootstrap env vars, see Deviations),
  `pgcrypto` in every database, and the `itemcode_public` read-only role per
  `docs/05-service-integration.md`, including `ALTER DEFAULT PRIVILEGES`.
- **`deploy/COOLIFY.md`** — create-the-app steps, the env var table, the secret-file mount
  procedure, database bootstrap, where Google OIDC credentials come from and the exact
  redirect URI, `MMOS_TRUSTED_PROXY_COUNT` verification with a real `curl`, deploying Service
  Desk as a sibling Coolify app, healthcheck/domain settings, and the quarterly restore-test
  checklist.
- **`deploy/NETWORK.md`** — concrete `ufw` rules, `wg-easy` as a Coolify container with
  per-person peers, split-horizon DNS setup for `os.m-mines.com`, DNS-01 configs for
  Coolify's built-in Traefik, standalone Caddy, and standalone Traefik, and the monthly
  VPN-peer-vs-active-employee audit as a checklist with a `psql`/`comm` command.
- **`scripts/backup.sh`** / **`scripts/restore.sh`** — nightly `pg_dump -Fc` of all four
  databases, `openssl enc -aes-256-cbc -pbkdf2` encryption, optional `rsync` off-box shipping,
  retention by mtime. `restore.sh` defaults to a scratch database
  (`<db>_restore_<UTC timestamp>`) and requires **both** `--force-live` and
  `RESTORE_CONFIRM=yes-overwrite-live` in the environment to ever target the live database name.
- **`.github/workflows/ci.yml`** — lint (`py_compile` hard gate + `ruff --exit-zero`
  informational), an env-contract regression check (see How to verify), `pytest` against a
  real `postgres:16.6-bookworm` GitHub Actions service container, then `docker compose build`
  followed by a full `docker compose up` + `curl /healthz` + `curl /.well-known/jwks.json`
  smoke test of the actual image — this is the one place in this run where the Docker
  acceptance criteria actually execute, since this build machine has no Docker.
- **`scripts/dev.sh`** / **`scripts/dev.ps1`** — bring up `postgres` from the compose file,
  wait for its healthcheck, run Alembic if `backend/alembic/` exists else fall back to
  `app.db.init_db()`, seed if `backend/app/seed.py` exists, then `uvicorn --reload`. Both
  guard for A1's not-yet-landed files so they'll do the right thing whichever lands first.
- **`deploy/.env.example`** — extended, not restructured: fixed the `MMOS_DATABASE_URL`
  comment to clarify compose overrides it, and appended a clearly-marked, all-commented-out
  section listing the six `MMOS_` settings that weren't already present
  (`MMOS_GOOGLE_REDIRECT_PATH`, `MMOS_SESSION_MAX_DAYS`, `MMOS_CLOCK_SKEW_SECONDS`,
  `MMOS_COOKIE_NAME`, `MMOS_PIN_MAX_ATTEMPTS`, `MMOS_PIN_LOCKOUT_MINUTES`) so the full env
  contract is visible in one file.

## Deviations

- **`init.sql` does not `CREATE ROLE mmos` / `CREATE DATABASE mmos`.** The compose file sets
  `POSTGRES_USER=mmos`, `POSTGRES_PASSWORD`, `POSTGRES_DB=mmos` on the `postgres` service, and
  the official Postgres image's own entrypoint already creates that role (as bootstrap
  superuser) and database *before* any `docker-entrypoint-initdb.d` script runs. A literal
  `CREATE ROLE mmos ...` in `init.sql` would fail with "role already exists" on every fresh
  volume. `init.sql` only creates the three *additional* databases/roles plus `itemcode_public`.
  Documented inline in the file and in `COOLIFY.md` §4.
- **`ALTER DEFAULT PRIVILEGES FOR ROLE itemcode`**, not the bare `ALTER DEFAULT PRIVILEGES` in
  `docs/05-service-integration.md`'s example. Default privileges are scoped to the role that
  *creates* the tables. The doc's snippet is written as if run by the owning role itself; this
  init script runs as the bootstrap superuser instead, so without `FOR ROLE itemcode` the
  grant would apply to tables the superuser creates, not to the ones Item Code Studio's own
  migrations will create — silently leaving the read-only role uncovered. Same net effect,
  correct in this execution context.
- **CI's lint step is two-tier, not one hard gate.** `py_compile` (stdlib, zero new
  dependencies, zero false-positive risk) is the only failing check; `ruff` runs
  `--exit-zero` (informational). A single strict style gate on a tree six agents are
  concurrently landing stub code into felt like the wrong failure mode to introduce — see
  Assumptions.
- **Postgres 16 pinned to `postgres:16.6-bookworm`**, not bare `postgres:16`, per the brief's
  "pinned by digest or exact tag, not `latest`." Same reasoning for `node:20.18.1-bookworm-slim`
  and `python:3.12.7-slim-bookworm`.

## Contract objections

None. `backend/app/config.py`, `middleware.py`, `main.py`, `db.py` were read closely and
matched exactly (see How to verify for the programmatic name comparison); nothing there looked
wrong from the infra side.

## Assumptions

- **`ruff==0.6.9` installed transiently in CI**, not added to `backend/requirements-dev.txt`
  (orchestrator-owned). It's a CI-runtime tool, not an application dependency, and it's never
  persisted — a fresh `pip install --quiet ruff==0.6.9` on every run. Flagging per the "no new
  dependencies... beyond that goes under Assumptions" rule anyway, since it is still something
  extra CI pulls in.
- **CI lint is intentionally non-blocking for style** (`ruff --exit-zero`). Only `py_compile`
  syntax errors fail the build. Rationale: five other agents are landing files into paths I
  don't own and can't fix, on the same run; a strict ruff gate risks failing CI on someone
  else's in-flight stub through no fault of the actual change being tested. If the orchestrator
  wants a hard style gate after run 1 settles, flip `--exit-zero` off in
  `.github/workflows/ci.yml`.
- **Base image tags** (`postgres:16.6-bookworm`, `node:20.18.1-bookworm-slim`,
  `python:3.12.7-slim-bookworm`) are exact tags I believe are valid as of this writing, chosen
  from memory rather than confirmed against the registries (no internet access from this
  agent). Confirm they still resolve before the first real build; digest-pin them for anything
  beyond a first deploy if reproducibility matters more than picking up patch releases.
- **`deploy/docker-compose.yml`'s `api.ports` maps `8000:8000` on the host.** This is what
  Coolify's Traefik (or a standalone reverse proxy) is expected to sit in front of — see
  `COOLIFY.md` §1 and §8. If Coolify's compose integration prefers `expose:` over `ports:`
  for its proxy discovery, that's a one-line change; I could not verify Coolify's actual
  behavior without a running Coolify instance.
- **`servicedesk`, `itemcode`, `att` role passwords in `init.sql` are static placeholders**
  (`CHANGE_ME_SERVICEDESK`, etc.), not templated from `deploy/.env`, because
  `docker-entrypoint-initdb.d` SQL files are not env-substituted by Postgres. Whoever runs this
  for real edits a local, gitignored copy first — documented in `COOLIFY.md` §4. This is a
  manual step, not automation, by necessity of the tool.
- **Windows PowerShell 5.1 cannot parse non-ASCII characters reliably in `.ps1` files on this
  machine** — an em dash (`—`) in a double-quoted string produced "missing string terminator" /
  "missing closing brace" parse errors from `[System.Management.Automation.Language.Parser]`
  even though the file is valid UTF-8. Found and fixed in `scripts/dev.ps1` (replaced with
  plain hyphens) during verification; worth knowing for any other agent writing `.ps1` files
  on this box.

## Not done

Nothing Docker-shaped could be *executed* on this machine — no Docker, no Docker Compose, per
the sprint amendment. Static checks were done instead (see How to verify). Concretely, not
run:

1. **`docker compose -f deploy/docker-compose.yml up -d` on this machine.** CI
   (`.github/workflows/ci.yml`) does run this on GitHub Actions' Ubuntu runner and asserts
   `/healthz` returns `{"ok":true,...,"db":"up"}` and JWKS returns an RSA key — that is the
   closest this run gets to proving it. Still needs a real run on the VPS:
   ```bash
   cp deploy/.env.example deploy/.env   # then fill in real values
   scripts/gen-signing-key.sh
   docker compose -f deploy/docker-compose.yml up -d
   curl http://localhost:8000/healthz
   ```
2. **The frontend Docker build stage against a real `frontend/package.json`.** A3 had not
   landed it as of writing. The Dockerfile's guard (`if [ -f package.json ]`) was read and
   reasoned through, not exercised against real frontend code. Verify once A3 lands:
   ```bash
   docker build -f deploy/Dockerfile -t mmos:check .
   ```
3. **`MMOS_TRUSTED_PROXY_COUNT` verified against a real Coolify/Traefik deployment.** The
   `curl -H "X-Forwarded-For: 10.8.0.1" ...` check in `COOLIFY.md` §6 needs a live instance
   behind the real proxy chain; not reachable from here.
4. **`scripts/backup.sh` / `scripts/restore.sh` run against real data.** Both pass `bash -n`
   and were read line by line, but `pg_dump`/`pg_restore`/`openssl enc` round-tripping was not
   exercised — there is no local Postgres. Verify:
   ```bash
   BACKUP_PASSPHRASE=test POSTGRES_PASSWORD=<real> PGHOST=localhost scripts/backup.sh
   BACKUP_PASSPHRASE=test POSTGRES_PASSWORD=<real> PGHOST=localhost scripts/restore.sh /var/backups/mmos/mmos_mmos_<timestamp>.dump.enc
   psql -h localhost -U mmos -d mmos_restore_<timestamp> -c 'select count(*) from employees;'
   ```
5. **`scripts/gen-signing-key.sh` was run** (see How to verify — it *was* exercised, once,
   locally, output discarded) but the resulting key was never fed through a real
   mint-token/verify-against-JWKS round trip end to end, since that needs the running API.
6. **The quarterly restore-test cadence itself** — documented as a checklist in
   `COOLIFY.md` §9, obviously not performable until there's a live deployment and a quarter
   has passed.
7. **`deploy/NETWORK.md`'s `ufw`, `wg-easy`, split-horizon DNS, and DNS-01 configs** are
   written to match `docs/06` and standard tool documentation, but none of it was applied to
   a real VPS, DNS zone, or WireGuard instance — there isn't one reachable from this machine.
8. **CI itself has never run** (no push happened from this sandbox — no git commands were run
   per the sprint amendment). Its YAML was validated (`yaml.safe_load`), each `run:` block's
   shell was checked with `bash -n`, the embedded Python heredoc was extracted and both syntax-
   and behavior-checked against the real repo files (see How to verify) — but GitHub Actions
   itself has not executed this workflow.

## How to verify

Everything below was actually run on this machine and its real output is quoted.

**1. Every `MMOS_` name in `deploy/.env.example` and `deploy/docker-compose.yml` matches a
real `Settings` field in `backend/app/config.py`** (the check the brief called the single most
likely silent-failure point), run programmatically:

```
Settings fields -> expected MMOS_ names: 23
In .env.example but not a Settings field: []
Settings field with no line (commented or not) in .env.example: []
In compose env override but not a Settings field: []
compose MMOS_ overrides: ['MMOS_DATABASE_URL']
```

Zero mismatches in both directions. This exact check is now also a CI step
("Verify MMOS_ env contract matches Settings" in `ci.yml`), so it's a standing regression
guard, not a one-off.

**2. `deploy/docker-compose.yml` parses as valid YAML** (`yaml` was available in
`backend/.venv`, contrary to the "may not be installed" caveat — confirmed and used directly
rather than adding a dependency):
```
deploy/docker-compose.yml OK ['services', 'secrets', 'volumes', 'networks']
```

**3. `.github/workflows/ci.yml` parses as valid YAML** with the expected single job and 12
steps (`yaml.safe_load` reports the `on:` key as boolean `True` rather than the string `"on"`
— a well-known PyYAML 1.1 quirk that affects every GitHub Actions workflow file ever written
this way; GitHub's own parser is unaffected, this is cosmetic to PyYAML only, not a bug in the
file).

**4. Every shell script passes `bash -n`** (syntax-only, no execution):
```
scripts/gen-signing-key.sh -> OK
scripts/backup.sh -> OK
scripts/restore.sh -> OK
scripts/dev.sh -> OK
```
Every `run:` block inside `ci.yml` was individually extracted and passed `bash -n` as well.

**5. `scripts/dev.ps1` parses cleanly** under
`[System.Management.Automation.Language.Parser]::ParseFile` — this caught a real bug (three
em dashes breaking the parser on this Windows PowerShell 5.1 install; fixed, see Assumptions)
and now reports `OK - no parse errors`.

**6. The embedded Python env-contract check inside `ci.yml` is not just syntactically valid —
it was extracted and actually run against the real repo files**, producing the same
`OK: 23 MMOS_ settings all accounted for in deploy/.env.example` result as check #1, confirming
the CI step will pass once it runs for real.

**7. `deploy/postgres/init.sql` was reviewed line by line** for statement ordering (role
creation before grants, `\connect` before per-database `GRANT`/`ALTER DEFAULT PRIVILEGES`,
`itemcode_public`'s grants issued while connected to the `itemcode` database) — no `psql` or
Postgres was available to parse it for real; see `## Not done` #1 for the command that
exercises it against a live server (compose's own `postgres` service runs it automatically on
first volume creation).

**8. `scripts/gen-signing-key.sh` was actually executed once**, against a throwaway path in
the scratchpad directory (not committed, not left in the repo), confirming `openssl genpkey`
produces a valid PKCS#8 RSA-2048 key, `chmod 600` applies, and the no-`--force`-overwrite
refusal fires on a second run against the same path.

**Definition-of-done items still requiring a real VPS or Docker host**: everything under
`## Not done`, with the exact commands to run listed there.
