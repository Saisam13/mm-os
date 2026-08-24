# B3 · Hardening

Scope actually delivered this pass, per the orchestrator's own scoped task for B3 (which
narrowed `agents/B3-hardening.md`'s fuller brief to: `docs/10-runbook.md`,
`docs/11-security-review.md`, `scripts/verify/**`, and this handoff, plus an explicit
assignment to bump the three base-image tags). `docs/12-floor-guide.md` and a full,
evidence-by-evidence walk of `docs/08`'s eight v1 criteria were named in
`agents/B3-hardening.md` but not in the task given for this run — not attempted; see
`## Not done`.

## Delivered

- **`docs/11-security-review.md`** — an adversarial read of the whole system, ranked by
  exploitability inside *this* deployment (VPN-only, `NETWORK_MODE=private`, ~74 accounts, a
  handful of registered services) rather than generic severity. Six findings (one HIGH but
  infrastructure-conditional, one HIGH but self-limiting, one MEDIUM deployment trap, one
  MEDIUM missing header, one LOW/MEDIUM theoretical-here ACL gap, one LOW dependency-hygiene
  roundup), plus a "Verified — not findings" section covering everything the task asked me to
  specifically check (the Google-link resolution path, the placeholder `pin_hash`, the
  `platform_admin` bypass removal, the deny-list end to end, the LLM control plane, cookies/
  sessions/admin-surface/injection). Every claim was reproduced — either traced through the
  exact code path or proven by a script — not asserted from reading alone.
- **`docs/10-runbook.md`** — deploy, roll back, read logs, restart; onboard/offboard (exact
  order, with the "why disabling Google alone isn't enough" reasoning inline); issue/reset a
  PIN (the same flow for all 73 people, no separate "no mailbox" path); register a new service
  end to end including the IT-self-grant note; signing-key rotation; emergency revoke one user;
  emergency disable-all-LLM (and its up-to-5-minute propagation delay); what to do when the
  deny-list poll fails; what to do when MM OS/Postgres/Frappe Cloud is down, certs expire, or a
  laptop is lost; where logs/backups/audit live and for how long; the restore procedure and
  quarterly test; the monthly VPN-peer audit; and a "known limits" section cross-referencing
  the security review's rate-limiting and org-chain findings so nobody discovers them by
  scaling into them.
- **Three new scripts under `scripts/verify/`**, each mechanical (one PASS/FAIL/SKIP line per
  check, non-zero exit on any FAIL), wired into `acceptance.sh local`'s existing run:
  - `verify-security.sh` (+ `_security_checks.py`) — admin-route 401/403, an unissued
    placeholder `pin_hash` rejecting every common guess plus the lockout firing, session cookie
    flags on a real login response, the deny-list end to end **including cross-service
    isolation** (a revocation scoped to one service is not visible to another's poll — not
    previously tested anywhere in this repo), token verification (`alg:none`, RS256→HS256
    confusion, wrong `aud`, a revoked subject), and the `X-Forwarded-For` trust-boundary
    behavior of `client_ip()` (proves it mechanically; whether that's *safe* depends on
    infrastructure the script can't see — see the security review's finding #1).
  - `verify-offboard.sh` (+ `_offboard_check.py`) — two modes. Default: a synthetic, one-process
    proof that deactivating a user via the real `PATCH /api/admin/users/{id}` route revokes the
    shell session (checked against a *second* client presenting the same raw cookie value, not
    just the first client's cached state), lands the subject on the deny-list every registered
    service will see, and leaves no live session row in the database. `--code EMPLOYEE_CODE
    --database-url URL`: a read-only real-world check against a live database for the on-call
    person to run after an actual offboarding.
  - `verify-backup.sh` — always runs `bash -n` on `backup.sh`/`restore.sh` and reports which
    Postgres client tools are on PATH; attempts a real dump→encrypt→decrypt→restore→row-count
    round trip only if `PGHOST` is reachable and `POSTGRES_PASSWORD`/`BACKUP_PASSPHRASE` are
    set — SKIP otherwise, never a fabricated PASS. Nothing on this build machine could exercise
    the real round trip (no Postgres); it did exercise every other check.
- **`scripts/verify/acceptance.sh`** extended (not restructured) — its local/full split and its
  SKIP-not-PASS philosophy are untouched; three new lines added to the local section, plus a
  header comment crediting the addition. Local mode now reports **15 passed, 0 failed, 5
  skipped** (up from B1's 12/0/5 — the 5 skips are still exactly the Docker-only full-mode
  checks).
- **Base image bumps**, the explicit orchestrator-assigned task
  (`handoff/ORCHESTRATOR.md`: "Bumping them is a B3 hardening task"). Checked current patch
  releases against the real Docker Hub API (not memory — this machine has network access):

  | File | Old | New | Confirmed via |
  |---|---|---|---|
  | `deploy/Dockerfile` (frontend-build stage) | `node:20.18.1-bookworm-slim` | `node:20.20.2-bookworm-slim` | `hub.docker.com/v2/repositories/library/node/tags`, pushed 2026-04-22 |
  | `deploy/Dockerfile` (runtime stage) | `python:3.12.7-slim-bookworm` | `python:3.12.14-slim-bookworm` | same API, `library/python`, pushed 2026-08-13 |
  | `deploy/docker-compose.yml` | `postgres:16.6-bookworm` | `postgres:16.15-bookworm` | same API, `library/postgres`, pushed 2026-08-13 |
  | `.github/workflows/ci.yml` (Postgres service container) | `postgres:16.6-bookworm` | `postgres:16.15-bookworm` | same, kept in sync with the compose file |

  All three stay pinned to an exact tag (never a floating `latest`/bare-minor tag), same minor
  line as before (`3.12`, `20`, `16`) so no dependency/behavior surface changed, only the patch
  level. Verified: `deploy/docker-compose.yml` and `.github/workflows/ci.yml` still parse as
  valid YAML after the edit; re-ran the full local test suite afterward (below) — nothing in
  it touches Docker, so this is a syntax/consistency check, not a build proof (see `## Not
  done`).

## Deviations

**Files touched outside `docs/10-11` and `scripts/verify/**`** — both are the base-image bump
above, both explicitly assigned to B3 by the orchestrator, and both are one-line version-string
edits with no behavioral ambiguity (same minor line, still pinned, no config/flag changes):

- `deploy/Dockerfile` — two `FROM` lines.
- `deploy/docker-compose.yml` — one `image:` line.
- `.github/workflows/ci.yml` — one `image:` line (kept consistent with the compose file so CI
  and the real deploy use the identical Postgres patch).

No other file outside my owned paths was edited. No application logic changed anywhere.

## Contract objections

None new. I read `backend/app/{config,models,db,security,deps,middleware,main}.py` (frozen
spine) closely while tracing the auth/token/revocation paths for the security review and found
nothing to object to — every finding in `docs/11` is either about a non-frozen router
(`routers/auth.py`'s missing PIN throttle), a `deploy/**` config choice (the published port), or
a documented-but-unset header in the frozen `middleware.py` (written up as a finding with the
exact fix, not applied, since I'm not the owner of that file and the guardrail is "findings over
fixes when a fix is more than a trivial, unambiguous one-liner" — a CSP header addition is small
but touches a frozen file, so it goes in the review, not the diff).

## Assumptions

1. **The task for this run narrows `agents/B3-hardening.md`'s brief.** The fuller brief also
   names `docs/12-floor-guide.md`, `verify-security.sh`/`verify-backup.sh`/`verify-offboard.sh`
   as separate named deliverables (delivered — see above), and a full v1-criteria evidence
   walk. The specific task given for this run asked for `docs/10-runbook.md`,
   `docs/11-security-review.md`, `scripts/verify/**`, and a handoff in `docs/09`'s six-section
   shape (this file) — I followed the specific task where the two differ, and did the three
   verify-scripts anyway since the task also said "you may extend `acceptance.sh`" and they are
   squarely inside `scripts/verify/**`.
2. **The Docker/`ufw` port-exposure finding (review finding #1) is reported as a high-confidence
   *class* of misconfiguration, not an observed live exploit** — there is no VPS or Docker host
   reachable from this build machine to actually test it against. I judged this worth ranking
   #1 anyway (rather than omitting it as "unverifiable") because the compose file as written
   today has exactly the shape (`ports: "8000:8000"`, no `DOCKER-USER` rule anywhere in the
   repo) that makes the well-documented Docker+ufw interaction apply, and because if true it
   invalidates the single premise (`docs/06`: "MM OS is not internet-facing") the rest of the
   threat model is built on. `deploy/COOLIFY.md` §6 already has the exact live test that would
   confirm or deny it — I did not invent a new one, I pointed at the existing one and explained
   why it needs to actually be run.
3. **The proposed fixes for findings #1, #2, and #5 are written up, not applied**, because each
   touches a file outside my owned paths (`deploy/docker-compose.yml`, `backend/app/routers/
   auth.py`, `backend/app/routers/agent.py`) and each has real behavioral ambiguity (which
   proxy topology Coolify actually uses; the right rate-limit threshold for a shared shop-floor
   terminal; which future services legitimately need the org-chain lookup) — exactly the
   guardrail's "if a fix is more than a few lines or has behavioral ambiguity, write it up
   instead."
4. **`scripts/verify/verify-security.sh`'s `X-Forwarded-For` check is reported as `WARN`, not
   `FAIL`**, because the code does exactly what `docs/06` documents (trust the Nth-from-right
   entry) — the risk is a deployment-topology question the script cannot see from inside one
   process, not a code defect this script can prove or disprove. Same reasoning for the missing
   CSP header (`WARN`, because it's a known, already-written-up, frozen-file gap, not a new
   regression this run introduced).
5. **`verify-offboard.sh --code`'s real-database mode was written but only exercised against
   its own argument-parsing and SQL, never against a real database** (no Postgres reachable
   here) — see `## Not done`.

## Not done

1. **`docs/12-floor-guide.md`** — not written. Not in the task given for this run (see
   `## Assumptions` #1); flagging explicitly since `agents/B3-hardening.md`'s fuller brief does
   name it.
2. **A full, evidence-by-evidence walk of all eight `docs/08-v1-plan.md` criteria** — not
   produced as a standalone section. Partial evidence exists scattered through
   `docs/11-security-review.md` (criterion 3, "removing a grant blocks access within 60
   seconds," is directly addressed there) and `docs/10-runbook.md` (criterion 8, the restore
   test, is written up as a procedure with its current unmet status stated in §14) — but nobody
   should read this handoff as a substitute for the dedicated section the fuller brief asks for.
3. **`docs/11-security-review.md` finding #1 (the Docker/`ufw` port question) was not tested
   live** — no Docker host or VPS reachable from this build machine. This is the single most
   consequential open question in the whole review; it needs `deploy/COOLIFY.md` §6's curl test
   run for real before this deployment should be trusted to actually be VPN-only.
4. **`scripts/verify/verify-backup.sh`'s real dump/restore round trip was never exercised
   against a live Postgres** — same limitation. Every other part of that script (syntax checks,
   tool-presence checks, the SKIP-with-reason path) was run and confirmed correct.
5. **The three base-image bumps were not rebuilt or re-run through CI** — no Docker on this
   machine. I confirmed the tags exist and are current via the Docker Hub API, and that the
   edited YAML/Dockerfile still parse, but "rebuild and re-run CI" (the orchestrator's own
   phrasing for this task) has not happened — that needs a push to trigger
   `.github/workflows/ci.yml` for real, or a manual `docker build`/`docker compose build` on a
   Docker host.
6. **`git log --all` for a possibly-committed-then-removed secret** (security review, "Secrets"
   section) — I was instructed not to run git commands; the orchestrator owns version control.
   Worth a one-time check: `git log --all -p -- '**/.env' '**/*.pem' '**/*.key'`.
7. **Everything already listed as "Not verified without a live deployment" in
   `docs/11-security-review.md`** — the real 60-second cross-process revocation SLA (proven
   once already by A4, not repeated), `MMOS_TRUSTED_PROXY_COUNT` against a real Traefik chain,
   and the Alembic migration against a real Postgres server (A1's own standing gap, restated
   here only because this review's trust in the schema depends on it).

## How to verify

All commands from the repo root; `PY` is `backend/.venv/Scripts/python.exe` (never bare
`python`).

```bash
# The three new scripts individually
bash scripts/verify/verify-security.sh      # expect: all PASS lines + 2 WARN lines, exit 0
bash scripts/verify/verify-offboard.sh      # expect: 7 PASS lines, exit 0
bash scripts/verify/verify-backup.sh        # expect: PASS on syntax/openssl, SKIP on the rest
                                              # (no Postgres client tools on this machine)

# The whole acceptance script, unchanged invocation, now with 3 more local-mode lines
bash scripts/verify/acceptance.sh local     # expect: 15 passed, 0 failed, 5 skipped

# Base-image edits are syntax/consistency only -- no Docker here to build them
grep -n "FROM \|image: postgres" deploy/Dockerfile deploy/docker-compose.yml .github/workflows/ci.yml
# expect: node:20.20.2-bookworm-slim, python:3.12.14-slim-bookworm, postgres:16.15-bookworm (x2)

# Dependency audits referenced in docs/11 finding #6
backend/.venv/Scripts/python.exe -m pip_audit -r backend/requirements.txt
backend/.venv/Scripts/python.exe -m pip_audit -r servicedesk/requirements.txt
cd frontend && npm audit --omit=dev && cd ..
cd servicedesk/frontend && npm audit --omit=dev && cd ../..
```

**Final tallies, re-confirmed at handoff:**

| Suite | Result |
|---|---|
| `backend/tests` | 72 passed, 1 skipped (`needs_postgres`) — unchanged from B1 |
| `servicedesk/tests` | 31 passed — unchanged |
| `packages/mmos-client-py/tests` | 15 passed — unchanged |
| `packages/embed/test/smoke.js` | 5 passed — unchanged |
| `frontend` | `tsc --noEmit` exit 0, `npm run build` OK — unchanged |
| `servicedesk/frontend` | `npm run build` OK — unchanged |
| `scripts/verify/acceptance.sh local` | **15 passed, 0 failed, 5 skipped** (was 12/0/5) |

Nothing B1 left green regressed.
