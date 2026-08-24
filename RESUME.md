# RESUME — how to pick this up cold

Written by the orchestrator during run 1, for the case where the session dies, credits run out,
or someone else takes over. **Read this file, then `handoff/ORCHESTRATOR.md`, then the
`handoff/a*.md` files that exist.** Everything below is fact on disk, not plan.

## Where the work lives

Agents write **real files directly into this repo** as they go. Nothing of value is held only
in a chat transcript. If every session ended right now, the code written so far would still be
here, and `git log` would show it.

## State of the build

- **Design direction: B, top nav and calm.** Locked in `brand/UI-DECISIONS.md` § Console
  direction and in `agents/A3-shell.md`. Directions A and C are still present in
  `demo/console-directions.html` on purpose; delete them only once the React shell is verified.
- **Run 1 (sprint A) launched 24 Aug 2026** — six agents in parallel, Sonnet 5, in this one
  tree. No worktrees, so there are **no branches to merge**; B1's merge step does not apply
  and B1 only has seams to fix and `scripts/verify/acceptance.sh` to write.
- **Two orchestrator changes** are documented in `handoff/ORCHESTRATOR.md`: the `User.grants`
  foreign-key fix in the frozen `models.py`, and the SQLite test harness. Do not re-litigate
  either; they are proven by `backend/tests/test_harness_smoke.py` (8 passing).

## How to tell what is done

```bash
git log --oneline                 # every checkpoint, newest first
ls handoff/                       # an a*.md file means that agent finished
git status --porcelain            # work not yet checkpointed
```

An agent is **done** when `handoff/a<n>-<slug>.md` exists. The two sections worth reading in
each are `## Contract objections` and `## Assumptions` — those are decisions a human owes an
answer to. `## Not done` tells you what it left behind.

Expected handoffs: `a1-identity`, `a2-tokens`, `a3-shell`, `a4-integration`, `a5-servicedesk`,
`a6-infra`. A missing file means that agent did not finish — its partial work is still on disk,
and the fix is to relaunch it with `agents/A<n>-*.md` as the brief plus a line naming what to
skip.

## How to restart an agent

Each brief in `agents/` is self-contained and was pasted as the whole first message. The
sprint-level amendments that override `agents/README.md` for this run:

1. No worktrees, no git commands by agents — the orchestrator owns version control.
2. Frozen spine read-only: `backend/app/{config,models,db,security,deps,middleware,main}.py`,
   `docs/01-09`, `backend/tests/conftest.py`, `backend/tests/test_harness_smoke.py`,
   `backend/requirements.txt`. Objections go in the handoff, never into an edit.
3. Python is `backend/.venv/Scripts/python.exe`. Node 24 / npm 11.
4. Tests run on SQLite via `backend/tests/conftest.py` fixtures (`db`, `client`,
   `make_employee`, `make_user`, `make_service`, `make_grant`, `sign_in`).
5. **No Docker, no Postgres on this machine.** Postgres-only work gets
   `@pytest.mark.needs_postgres` and a line under `## Not done`.
6. No Google OIDC credentials. Build to the env contract; fake the token exchange at the
   `httpx` boundary.
7. Read the employee spreadsheet at `Desktop/Erp Imp/Employee_Role_Access_Mapping.xlsx` in
   place. Never copy real names or work emails into this repo — `data/` is not gitignored for
   `.xlsx` and it would enter git history.

## Verify the machine still works

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q
```

## Known gaps, deferred deliberately

Unproven here because the machine has neither Docker nor Postgres: `docker compose up`, the
image build, `pgcrypto`, JSONB operators, the hand-written Alembic migration against a real
server, and foreign-key cascades (SQLite does not enforce FKs without the pragma — enable it
at the B1 boundary). No Google sign-in has ever been performed; no OIDC client exists yet.

Docker Desktop needs an elevated shell and a reboot, so it is the owner's step:
`wsl --install`, reboot, then
`winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements`.

## Checkpointing

A loop commits everything **every three minutes** while a run is in progress, so an interrupted
session loses at most three minutes of agent output. Commits titled
`checkpoint: run 1 in progress (n)` are machine-made and safe to squash later.

The script lives outside the repo, in the session scratchpad under
`%LOCALAPPDATA%\Temp\claude\C--Users-Anura-OneDrive-Desktop-MM-OS\<session>\scratchpad\checkpoint.sh`
— it is orchestration, not product. To stop it, create the stop file:

```bash
touch "C:/Users/Anura/OneDrive/Desktop/MM OS/.checkpoint-stop"
```

There is nothing precious in the script. To restart checkpointing in a new session, any loop
that runs `git add -A && git commit` on a timer will do.

---

# Run 1 status at the session-limit interruption

**24 Aug 2026.** The Anthropic session limit was hit (resets 05:50 Asia/Kolkata) and three
agents were terminated mid-work: A1, A3, A5. **Nothing was lost** — the 3-minute checkpoint
loop had already committed everything, and the working tree was clean at the moment of failure.
Verified after the interruption: frozen spine still carries only the one documented `models.py`
fix, and the backend suite is green.

## Verified state, by agent

| Agent | Code | Tests | Handoff | Outstanding |
|---|---|---|---|---|
| **A1** identity | complete for its *original* brief | `55 passed, 1 skipped` | yes | **the auth revision was never applied** — see below |
| **A2** tokens | complete | 25 own + suite green | yes | none |
| **A3** shell | complete, `tsc --noEmit` exit 0, `npm run build` OK (63 modules, dist emitted) | no test suite (build is the gate) | **no** | visual/behavioural verification, then the handoff |
| **A4** kit | complete | 15 py + 5 js, live 60s revocation proven | yes | none |
| **A5** desk | backend complete; **frontend incomplete** — `src/main.jsx` imports `./App.jsx`, which does not exist, so `npm run build` fails | `30 passed` (backend) | **no** | finish the frontend, then the handoff |
| **A6** infra | complete | statically verified; Docker runs in CI only | yes | none |

Re-verify any of this locally — none of it costs API tokens:

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q
```

```bash
cd servicedesk && ../backend/.venv/Scripts/python.exe -m pytest -q
```

```bash
cd frontend && npx tsc --noEmit && npm run build
```

## Outstanding work, in priority order

**1 · A1's auth revision — not started.** `seed.py` still classifies by email domain (its
original approach) and there is no Google-linking flow in `auth.py`. The owner's decision is
recorded under "Owner decisions taken mid-run" in `handoff/ORCHESTRATOR.md`; implement exactly
that: all 73 employees get a PIN account; Google sign-in open to any address; a
link-your-Google-account flow that attaches a verified Google identity **only to the currently
authenticated user**, setting `login_email`, flipping `auth_type` to `'google'` and keeping
`pin_hash` so PIN login still works; and the `hd` check kept **only for auto-provisioning**, so
an unknown gmail address still cannot create an account while a linked one signs in. Require
`email_verified`. Match on email — there is no `google_sub` column and one must not be added.
Handle the `login_email` uniqueness collision with a clear error that does not let anyone
enumerate who has linked what. Test both `hd` branches. Then update `handoff/a1-identity.md`,
resolving its Assumption 4 and recording the conditional `hd` behaviour under Deviations.

**2 · A5's frontend.** Backend and its 30 tests are done and green. It stopped immediately
before writing `App.jsx`. All four views still have to land: my requests, department queue with
assignee, IT agent console, approver decisions. Then `handoff/a5-servicedesk.md`.

**3 · A3's verification and handoff.** The code builds and typechecks, so this is confirming
direction B renders as intended and writing `handoff/a3-shell.md` — including the missing
public-services endpoint, which its brief told it to raise.

## Resuming

Each of the three can be restarted with its original brief from `agents/`, plus the sprint
amendments listed earlier in this file, plus a line naming what is already done so it does not
redo it. A1 additionally needs the auth-revision instruction in item 1 above.

After that, run 2 is B1 (assembly) — which has **no branches to merge**, only seams to fix and
`scripts/verify/acceptance.sh` to write — then B2 and B3.

## Seams B1 must reconcile (already known)

- **Error shape**: `deps.py` raises `HTTPException(detail={...})`, so FastAPI returns
  `{"detail": {...}}`, not the flat `{error, message, request_id}` that `docs/03` documents.
  App-wide; needs one exception handler in `main.py`. Raised by A2.
- **Revocations path**: `docs/03` shows `GET /api/revocations`, but `main.py`'s prefix puts it
  at `/api/agent/revocations`. A2 followed the code; A4's poller must agree.
- **`POST /_mmos/session`** is specified in no doc, yet is the one browser-to-service wire
  format. A4 designed it and named the cookie `{slug}_mmos_at` by its own convention. Pin it
  down in `docs/05` before another service invents something different.
- **`public_paths`** are prefixes, not exact matches — the only reading under which `docs/05`'s
  own example is public. Tighten the doc.
- **`revocations.purge_after`** has no default in `models.py` though `docs/02` gives it one;
  A1 and A2 both supply it explicitly at every call site.
- **Base images** are real but ~a year old; bumping them is a B3 hardening task.

---

# Run 2 · B1 complete

**Verified by the orchestrator after B1 finished**, not taken on report:

| Suite | Result |
|---|---|
| `backend/tests` | **72 passed**, 1 skipped (`needs_postgres`) |
| `servicedesk/tests` | 31 passed |
| `packages/mmos-client-py/tests` | 15 passed |
| `packages/embed/test/smoke.js` | 5 passed |
| both frontend builds | clean |
| `scripts/verify/acceptance.sh` | **12 passed, 0 failed, 5 skipped** (Docker checks skip with the exact command to run on a Docker host) |

**Frozen-spine edits, total, across the entire build:** `models.py` (the orchestrator's
`User.grants` FK fix) and `main.py` (B1's single `HTTPException` handler, +31 lines). Nothing
else in the spine changed.

**B1 found a live bug**, which is why the revocations seam mattered: A4's `DenyListPoller` was
polling `/api/revocations` — the inconsistent example in `docs/03` — rather than the real
`/api/agent/revocations`. In production the 60-second revocation SLA would have silently never
fired. Fixed in `_denylist.py`, its test, and the echo-service stub.

**Also resolved:** the error envelope is now flat `{error, message, request_id}` app-wide (11
stale test assertions corrected); Service Desk now constructs and installs A4's real `MMOS` kit
in `AUTH_MODE=http`, replacing a verify path that never actually checked revocation; roles serve
`description` and grants serve `granted_by`, so the two locked Access-page capabilities work.

**A deliberate security decision, not an inherited default:** `platform_admin` no longer
bypasses a service's own role check anywhere — it does not auto-see private tickets and does not
auto-get agent-console access. If that turns out to be wrong operationally, it is a policy
change, not a bug fix.

**Endpoints added:** `GET /api/public/services` (names + launch URLs only) and
`GET /api/agent/org/chain` (service-authenticated, minimum disclosure, degrades when no manager
chain exists — only 11 of 73 resolve from the sheet).

## What remains

- **B2 · Retrofit** — moves ATT Platform and Item Code Studio onto MM OS and deletes their PIN
  gates. **Works in other repos on the Desktop**, which are tools people use daily. Sequencing
  advice: do this *after* MM OS has actually run against real Postgres, since pointing a
  live tool at an unproven identity provider is the risky order.
- **B3 · Hardening** — `docs/10-runbook.md`, `docs/11-security-review.md`, more of
  `scripts/verify/**`. Stays inside this repo, so it is safe to run any time. Its known inbox:
  bump the year-old base images, and review the `platform_admin` decision above.
- **Docker and Postgres** still absent locally; the Alembic migration has still never run
  against a real server. `wsl --install`, reboot, then
  `winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements`.

---

# Run 2 complete — all nine agents done

**24 Aug 2026.** Sprint A (A1–A6), B1, B3 and B2 have all finished. Verified state:

| Check | Result |
|---|---|
| `scripts/verify/acceptance.sh full` | **21 passed, 0 failed, 0 skipped** |
| `backend/tests` | 75 passed, 1 skipped (`needs_postgres`) |
| `servicedesk/tests` | 31 passed |
| `packages/mmos-client-py/tests` | 15 passed |
| ATT retrofit suite (stub MM OS + echo service) | 19 passed |
| ATT boot-mode matrix | 4 passed |
| `alembic check` against real Postgres | no drift |
| Backup → restore into scratch DB | performed and verified |

**Frozen-spine edits, final total: four.** `models.py` (the `User.grants` FK fix, plus four
index declarations), `main.py` (B1's error-envelope handler), `middleware.py` (the CSP header).
Everything else in the spine is byte-identical to commit `844bc72`.

## The ATT retrofit

Branch `mmos-retrofit` in `C:\Users\Anura\OneDrive\Desktop\ATT_Platform`, two commits
(`2be2337`, `7a60e4a`). **`master` is untouched at `b794201`, and nothing was pushed.** Merging
it is a human decision, not something an agent should do.

The PIN gate is deleted, not disabled. The MM OS client is vendored into
`backend/vendor/mmos_client` because ATT has no path to the MM OS monorepo at deploy time.

**ATT's environment contract — read this before deploying it:**

| `MMOS_SERVICE_KEY` | `ATT_DEV_NO_AUTH` | Result |
|---|---|---|
| unset | unset | **refuses to start** |
| unset | `1` | boots open, with a red banner and a visibly fake user |
| set | unset | boots with real MM OS auth |
| set | `1` | **refuses to start** (contradictory) |

That matrix exists because the first implementation treated a *missing* `MMOS_SERVICE_KEY` as
"no auth needed" and handed out a synthetic admin — fail-open. Having just deleted a PIN gate,
that would have been a net loss in security. Absence of configuration must never mean absence
of authentication. `scripts/verify_boot_modes.py` in the ATT repo proves all four cases with
real subprocess boots.

## Human steps that remain

1. **Register the `att` service in MM OS** — three curl commands, verbatim in
   `handoff/b2-retrofit.md`, plus a real `MMOS_SERVICE_KEY`. ATT cannot authenticate anyone
   until this is done.
2. **Merge `mmos-retrofit`** in the ATT repo when you are ready. Nothing is pushed.
3. **Drop `ports: 8000:8000`** from `deploy/docker-compose.yml` before or during the first VPS
   deploy, and let Coolify's Traefik reach the container over the internal network. This is
   B3's top finding: Docker's iptables integration bypasses `ufw` for published ports, which
   could make "not internet-facing" false. `deploy/COOLIFY.md` §6 has the curl that settles it.
4. **Set `OFFSITE_DEST`** or backups never leave the VPS (`docs/06` requires off-box storage).
   Note `rsync` is **not** in the postgres image, so the scheduler needs it on the host.
5. **Replace the placeholder passwords** in `deploy/postgres/init.sql` in a local, gitignored
   copy before the first real deploy.
6. **Decide about Item Code Studio.** It does not exist — searched Desktop, Documents, OneDrive
   and `D:`. Only spreadsheet scripts in `Erp Imp/Files created for tasks/`. MM OS's seed carries
   an `itemcode` registry row with a placeholder URL, so the tile appears when the service does.
   Building it is a **new service** (own container, DB, repo), not a retrofit.

## Local test artifacts on this machine

`deploy/.env` (throwaway generated password) and `deploy/secrets/mmos_signing_key.pem`. Both
gitignored and confirmed invisible to `git status`. **Neither is a real credential.** Generate
real ones on the VPS with `scripts/gen-signing-key.sh`.

## Windows-only gotcha

Driving `docker compose exec -e SOMEPATH=/tmp/...` from Git Bash gets the POSIX path rewritten
by MSYS, so the container sees a literal `/C:/Users/...`. Set `MSYS_NO_PATHCONV=1`. This cannot
happen on the Linux VPS.

---

# LIVE DEMO — deployed 25 Aug 2026, ~05:30 IST

Two applications are running on the company Coolify server, both from `Saisam13/mm-os`
(private) over a read-only deploy key.

| What | URL | Coolify app |
|---|---|---|
| **MM OS shell** | http://hrxd6lgu3h7qpnkbpy2mqgdc.200.234.36.153.sslip.io | `mmos` |
| **Service Desk** | http://uthjgvwpvx68afqgrz8gf9rh.200.234.36.153.sslip.io | `servicedesk` |

Databases: `mmos-postgres` and `servicedesk-postgres`, both Coolify-managed.

## Demo logins (MM OS) — PIN `1234` for all five

| Code | Name | Department | Role |
|---|---|---|---|
| `MM-ITADMIN` | IT Administrator | Information Technology | platform admin |
| `MM05` | Mandaleshvar Sharma | P-Spoke | IT agent |
| `MM81` | Chandrashekhar Keshav Kalvit | Projects | approver (L4) |
| `MM88` | MAMATESH UDAY NAIK | Projects | requester — **reports to MM81** |
| `MM33` | Hardhik Pendurthi | StratOps | requester |

23 people across 9 departments are seeded. Everyone else has a placeholder PIN and cannot
sign in — that is the truthful state of a batched rollout.

## Verified working on the live instances

- PIN login, `/api/me`, service tiles per person (grants are deliberately uneven).
- All three request types: **software** (`SD-2026-0001`, open, no approval), **hardware**
  (`SD-2026-0002`, open, no approval), **automation** (`AR-2026-0001`).
- The full automation chain, driven end to end:
  `submitted → it_review → proposal_ready → manager_review → approved`, appearing in the
  approver's queue and recording the decision against the proposal.

## Service Desk personas are separate from MM OS accounts

Service Desk runs `AUTH_MODE=stub`, so it has its own sign-in with four personas —
`operator`, `supervisor`, `hod`, `apex` — unrelated to the MM OS employee codes. That follows
directly from the decision to drop SSO for now: each service keeps its own login. Worth
knowing before the meeting, because the names on screen will not match between the two.

## Known gaps, none blocking

- **No SLA targets are configured** — the tab works, the table is empty. Adding one live is a
  reasonable thing to demonstrate.
- **Creating a proposal while a ticket is still `submitted`** is accepted but does not advance
  the state; the transition only happens from `it_review`. Harmless but confusing.
- Service Desk is seeded `is_active=False` in the MM OS registry, so it is not shown as a tile.
  Flip it and set `MMOS_SVC_SERVICEDESK_URL` to the URL above if you want it in the list.
- The old `mm-os` Coolify app (`v9vem9vm1dolgnatyh1euaev`) is a dead first attempt that never
  routed. Delete it in the UI; `mmos` is the live one.
- `minimines-ocr` has been dead since 17 Aug; `ocr-service` is the live OCR. Safe to delete.

## MUST be reverted after the meeting

- `MMOS_NETWORK_MODE=public` → back to `private` with the CIDR allowlist.
- Rotate the Coolify API token — it was sent over plain HTTP.
- `backend/app/demo_seed.py` holds 23 real employee names (no emails). Delete it once the real
  batched rollout replaces it.
- Demo PINs are all `1234`.

## Final verification — 25 Aug 2026, 07:50 IST

Everything below was exercised against the live servers, not tests.

| Check | Result |
|---|---|
| Item Code Studio, Sales Hub, ERPNext, OCR, MM OS, Service Desk | all **HTTP 200** |
| All five MM OS logins | working, each with tiles that open |
| Three ticket types raised | `SD-2026-0003` software, `SD-2026-0004` hardware, `AR-2026-0003` automation |
| Full approval chain | MM88 raised → MM05 reviewed and proposed → **MM81 approved** |
| Proposal on a `submitted` ticket | correctly rejected `409 wrong_status` |
| SLA targets | **36 rows** — 9 departments x low/normal/high/urgent |

**Approval routing as configured:** a request from **Projects** goes to **MM81**; anything else
falls to the default approver, **MM-ITADMIN**. The preview box on the Approval Routing screen
shows this for any combination.

**Two traps worth remembering.** The seed is idempotent, which protects an admin's edits but
also means **stale rows are never corrected** — the approval rule kept pointing at the old stub
approver until it was updated by hand. And deactivating a service silently strips it from
everyone's tiles, which is correct but left two demo accounts with an empty service list until
they were re-granted.

Documents (private artifacts): MM OS, Item Code Studio, Sales Hub, and the internal Runbook.
