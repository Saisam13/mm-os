# B1 · Assembly and acceptance (run 2)

Scope, per `handoff/ORCHESTRATOR.md`'s "Run 1 complete · seam inventory for B1": sections A
and B of the seam inventory, plus `scripts/verify/acceptance.sh`. Section C (deferred ideas)
was not touched. There was nothing to merge — six agents worked in one tree on exclusive
paths, so this pass is seams only, exactly as the orchestrator's note said.

## Delivered

**Section A — must fix, blocking**

1. **App-wide error envelope.** `backend/app/main.py` (frozen spine) gained one
   `@app.exception_handler(HTTPException)` that flattens any dict-valued `HTTPException.detail`
   to the top level — `{"error","message","request_id"}`, matching `docs/03-api-contract.md`
   exactly, with `request_id` read from `request.state.request_id` (set by the frozen
   `RequestId` middleware) and any extra key a router put in `detail` (e.g. `require_role`'s
   `need`/`have`) riding along unchanged. No router changed. Updated the 11 assertions in
   `backend/tests/test_identity.py` and `backend/tests/test_platform.py` that asserted on the
   old `response.json()["detail"]["error"]` nesting — including the one comparing two error
   bodies for equality, which now compares `error`+`message` rather than the whole body (the
   two responses now carry different `request_id`s, correctly).

2. **Revocations path.** Confirmed `backend/app/main.py` mounts `agent.router` at
   `/api/agent`, so the real path is `GET /api/agent/revocations` (A2's contract objection —
   the doc's bare `/api/revocations` example is internally inconsistent with the same doc's
   own `/api/agent/heartbeat` and `/api/agent/config` examples). `packages/mmos-client-py`'s
   `DenyListPoller` was actually polling the bare path from the doc — this is a real bug, not
   a doc nit: the 60-second revocation SLA would silently never fire against the real MM OS.
   Fixed in `packages/mmos-client-py/mmos_client/_denylist.py` (both the docstring and the
   live `GET` call), plus the two places that stub MM OS for tests/demos:
   `packages/mmos-client-py/tests/test_mmos_client.py` and `examples/echo-service/stub_mmos.py`.

3. **The A4 ↔ A5 auth seam.** Adopted A4's `mmos-client-py` kit as the standard, in a way
   that does not disturb Service Desk's 31 passing tests (all of which run `AUTH_MODE=stub`):
   - Installed `mmos-client-py` editable into the shared `backend/.venv`
     (`pip install -e packages/mmos-client-py --no-deps`) so `servicedesk/app` can import it —
     first-party, in-repo code, not a new external dependency.
   - `servicedesk/app/mmos_seam.py`: added `get_real_mmos()`, a lazily-constructed shared
     `mmos_client.core.MMOS` instance used only when `auth_mode="http"`. `_decode_http_token`
     now calls its `_verify()` (full ordered check: kid → signature → iss → aud → exp/iat →
     deny-list → roles, with a live deny-list poller) instead of the old bare
     `jose.jwt.decode` — which never checked revocation at all in "http" mode, since nothing
     populated its local `_revoked_subs`/`_revoked_jti` sets there. This was a real gap, not
     cosmetic: a revoked Service Desk user's token would have kept working forever against a
     real MM OS.
   - `servicedesk/app/main.py` calls `get_real_mmos().install(app)` when `auth_mode="http"`,
     wiring the real two-call handoff (`GET /_mmos/accept` → `POST /_mmos/session`, not A5's
     original one-call `POST /_mmos/accept`), the cookie name `servicedesk_mmos_at`
     (`{slug}_mmos_at`), and starting the real deny-list poller and heartbeat threads.
     `servicedesk/app/routers/mmos.py`'s own `/_mmos/accept`/`/_mmos/health` are now gated to
     `auth_mode="stub"` only, so there is exactly one live implementation of each path at a
     time. Cookie renamed the same way in stub mode too (`COOKIE_NAME` constant, shared).
   - **The `platform_admin` bypass question, answered deliberately, not inherited silently:**
     removed the bypass from `require_role` (`mmos_seam.py`), `can_see_full`
     (`app/privacy.py`), and both copies of `_is_agent` (`routers/tickets.py`,
     `routers/comments.py`). MM OS's `platform_admin` flag is a platform concept; Service
     Desk's roles (`agent`, `admin`) are its own vocabulary, exactly matching A4's
     `mmos_client.core.require_role`. Concretely: a platform admin no longer silently sees
     private ticket bodies (the locked decision named in the seam inventory), and no longer
     silently gets agent-console access either — "access to the console" and "visibility of
     private content" turned out to have the same answer once actually decided: neither
     inherits from `platform_admin`; both come from a real Service Desk grant, like anyone
     else. No test in this repo ever set `platform_admin=True`, so this changed no test
     outcomes — verified by grep before touching it.
   - **Verified live**, not just by inspection: constructed the Service Desk app with
     `AUTH_MODE=http` and a dummy service key/URL and drove it through `TestClient` (which
     runs real ASGI startup/shutdown). Confirmed exactly one `/_mmos/accept` (GET) and one
     `/_mmos/session` (POST) route exist (no duplicate registration between the stub router
     and the installed kit), `GET /_mmos/health` returns `200 {"ok":true,...}` from the real
     kit, and an unauthenticated `GET /api/tickets/mine` returns the real kit's flat
     `401 {"error":"missing_token"}` from its fail-closed ASGI middleware — proving requests
     never reach a router without a verified token once "http" mode is wired in.

4. **Admin API shape drift** (`backend/app/routers/platform.py`, resolved in favour of the
   locked UI capabilities in `brand/UI-DECISIONS.md`, per the orchestrator's explicit
   instruction):
   - `_service_out`'s `roles[]` now serialises `description` (was already a column on the
     frozen `ServiceRole` model, just never read out) and `id`. "Role meanings shown inline"
     now has a data source.
   - `_grant_out` is now nested — `{id, user:{id,name,employee_code}, service:{slug,name},
     role:{key,name}, granted_by:{id,name}|null, reason, expires_at, created_at}` — instead
     of the old flat `{user_id, service_slug, role}` with no name or granter anywhere. "Who
     granted it and when" now has a data source. `granted_by` is `null` for grants that
     predate any admin (there are none from the real sheet — proposed ERP-access notes are
     never auto-written as grants, per `app/seed.py`).
   - `POST /services/{slug}/roles` returns the same enriched role shape.
   - `GET /api/admin/llm` rows gained `name` (the service's display name, already available
     from the same join) and renamed `usage` → `usage_30d` to match the window the query
     already computes (`cutoff = today - 30 days`).
   - `GET /api/admin/audit` entries gained nested `actor:{id,name}|null` and
     `service:{slug,name}|null` (batched lookups, not per-row) — this is what actually lets
     `audit_log` "answer who granted what, to whom, when" (`docs/08`'s v1 definition of done
     #6), which an id-only field could not.
   - **`frontend/src/api/client.ts`** reconciled to the real (still-wrapped) response shapes
     — `{services:[...]}`, `{grants:[...]}`, `{registrations:[...]}`, `{entries:[...]}` are
     unwrapped there, `bulkGrant`'s `{created,skipped}` is mapped to the `{count}` shape the
     page components already expect, and `listEmployees` now joins `/api/admin/employees` +
     `/api/admin/users` client-side (on `employee_id`) into the one-joined-row shape
     `PeoplePage.tsx` was built against — all in the one file that already exists specifically
     to translate wire shapes for the page components (`client.ts`'s own docstring), rather
     than touching every admin page. `npx tsc --noEmit` and `npm run build` both still pass.

**Section B — missing endpoints, in scope**

5. **`GET /api/public/services`** — added to `backend/app/routers/me.py` (already mounted at
   `/api` by frozen `main.py`, so no spine edit needed). No auth dependency. Returns exactly
   `{slug, name, launch_url, session_owner}` per active service — `session_owner` is
   `"service"` for `launch_mode="external"` (ERPNext, Twenty — they own their own sign-in)
   and `"mmos"` otherwise, matching A3's own inference in `serviceKind.ts` and
   `brand/UI-DECISIONS.md`'s entry-page rule. `frontend/src/api/client.ts`'s
   `getPublicServices` already unwrapped `.services` correctly (A3 built it against the
   documented shape), so no frontend change was needed there.

6. **`GET /api/agent/org/chain?sub=`** — added to `backend/app/routers/agent.py`, behind
   `require_service_key` like heartbeat/config/revocations. Walks `Employee.manager_id`
   up from the given subject, requester-first, returning exactly the fields
   `servicedesk/app/org_chart.py::PersonNode`/`HttpOrgChartClient` already assumed:
   `sub, employee_code, full_name, department, approval_level, is_approver, manager_sub,
   email` — nothing else (no band, division, job title — minimum disclosure, not the
   `/api/admin/employees` directory dump A5's handoff correctly refused to have Service Desk
   depend on). Mounted under `/api/agent` (not the bare `/api/org/chain` A5's client
   originally guessed) to match the one real convention already established for every other
   service-authenticated call — see item 2 above; `servicedesk/app/org_chart.py`'s
   `HttpOrgChartClient` URL updated to match. Degrades gracefully by design: an unknown
   `sub`, a manager with no `manager_id`, or a manager whose `Employee` row has no `User`
   account yet all simply end the chain where they are (returns a shorter `chain`, never an
   error) — necessary given A1's finding that only 11 of 73 real managers resolve at all.
   Covered by four new tests in `backend/tests/test_b1_seams.py` (full chain, no-manager,
   unknown-subject, missing-service-key).

**`scripts/verify/acceptance.sh`** (new, plus its helper `scripts/verify/_seed_dry_run.py`) —
see `## Acceptance results` below for the actual run.

## Deviations

**Frozen-spine edit (the only one this run made beyond the orchestrator's own two from
run 1):**

- `backend/app/main.py` — added the `@app.exception_handler(HTTPException)` described in
  item 1 above. Nothing else in the file changed: no router wiring, no middleware order, no
  new mounts beyond the handler itself. This is exactly the fix the orchestrator's seam
  inventory named as belonging in `main.py`.

**Other edits, none to frozen files, listed because they touch paths another agent owned in
run 1** (expected — this is what "assembly" means; the seam inventory named each of these
explicitly):

- `backend/app/routers/{me,agent,platform}.py` — items 4–6 above (A1's and A2's routers).
- `backend/tests/{test_identity,test_platform}.py` — the 11 envelope-assertion updates in
  item 1 (A1's and A2's test files). `backend/tests/conftest.py` and
  `test_harness_smoke.py` (orchestrator-owned) were not touched; `test_b1_seams.py` is a new
  file, not an edit to either.
- `packages/mmos-client-py/mmos_client/_denylist.py`,
  `packages/mmos-client-py/tests/test_mmos_client.py`,
  `examples/echo-service/stub_mmos.py` — the revocations-path fix (item 2, A4's paths).
- `servicedesk/app/{mmos_seam,main,privacy}.py`,
  `servicedesk/app/routers/{mmos,tickets,comments}.py`,
  `servicedesk/app/org_chart.py` — the auth-seam rewiring (item 3, A5's paths).
- `frontend/src/api/client.ts` — the shape reconciliation (item 4, A3's path).

## Contract objections

None new. Every objection the six agents raised in run 1 that fell inside sections A/B is
resolved above (error envelope, revocations path, the auth seam, the admin shape drift, the
missing public-services and org-chain endpoints). The objections that fell in section C
(pending access requests, session lists, `target_id` audit filter, `login_email` immutability,
notifying a non-actor by email) are explicitly deferred by the orchestrator's own seam
inventory and were not touched.

One standing doc inconsistency is worth re-stating rather than re-litigating: `docs/01`,
`docs/03`'s own prose example, `docs/05`, and this repo's top-level `README.md` all still say
`/api/revocations` (no `/agent`). A2 already flagged this in run 1 and left the frozen docs
alone, correctly — `docs/01-08` are frozen spine, not B1's to edit either. The code is now
internally consistent (every real caller uses `/api/agent/revocations`); the docs are not,
and that gap is pre-existing, not introduced or widened by this pass.

## Assumptions

1. **`GET /api/agent/org/chain` has no per-endpoint service ACL** — any service holding a
   valid service key can walk any subject's manager chain, the same trust boundary
   heartbeat/config/revocations already use. There is no infrastructure in this build for
   "only Service Desk may call this," and adding one would be a new feature, not a seam fix.
   Minimum disclosure is enforced on *what* the endpoint returns (the seven `PersonNode`
   fields, nothing else), not on *who* may call it.
2. **The org-chain walk caps at 20 hops** as a defence against an accidental `manager_id`
   cycle in the data — arbitrary, but the real org is ~73 people and A1's own resolution
   found only 11 real manager links, so no real chain gets near this.
3. **`frontend/src/api/client.ts` is the reconciliation point for the admin wire-shape
   drift**, not a backend rewrite to bare arrays or a per-page frontend rewrite. This keeps
   the diff to one file that already exists specifically to translate wire shapes (its own
   docstring says so), rather than touching `PeoplePage.tsx`/`AccessPage.tsx`/
   `ServicesAdminPage.tsx`/`LlmPage.tsx`/`AuditPage.tsx`, all of which were already built and
   verified against the mock's shapes. `listEmployees`'s client-side join fetches up to 200
   employees and 200 users (two requests) rather than paginating — fine at MiniMines' scale
   (~74 people), would need revisiting if the company's headcount grows an order of
   magnitude.
4. **`pip install -e packages/mmos-client-py --no-deps` into the shared `backend/.venv`** —
   not a new external dependency (first-party, already in this repo, already used elsewhere
   via `sys.path` tricks by A4's own tests), but it does modify the shared venv's installed
   packages. `backend/requirements.txt` (orchestrator-owned) was not touched; this needs
   re-running on a fresh checkout — see `## How to verify`.
5. **`scripts/verify/_seed_dry_run.py` imports `backend/tests/conftest.py` directly** to
   reuse its JSONB→JSON and naive→UTC-datetime SQLite compiler shims, rather than
   duplicating them. `conftest.py` is orchestrator-owned and read-only; this only imports it
   (executing its module-level env-var defaults and compiler registrations), never edits it,
   and runs no test or fixture from it.
6. **Audit-log actor/service name enrichment batches by distinct id**, not per-row — at most
   two extra queries per page of up to 200 rows (limited by the existing `limit`/`cursor`
   pagination), not O(n).

## Not done

1. **`scripts/verify/acceptance.sh full` is untested against a real Docker host** — there is
   no Docker on this machine (docs/09's standing sprint amendment). The script detects this
   (`command -v docker`) and reports all five full-mode checks as `SKIP` with that reason,
   rather than failing or fabricating a pass. It has never actually run the `docker build` /
   `docker compose up` / `alembic upgrade head` / `/healthz` / JWKS sequence for real — that
   still needs a run on a Docker host or the VPS, exactly as A6's own handoff already said
   about the rest of `deploy/**`.
2. **The Service Desk `AUTH_MODE=http` path was verified live at the ASGI/middleware level
   (see item 3), but never with an actual signed JWT round-tripped from a real or stub MM OS
   through Service Desk's real cookie flow.** `mmos-client-py`'s own 15 tests already prove
   the cryptographic verification path in isolation (valid/expired/tampered/alg-confusion/
   revoked), and `backend/tests/test_security.py` proves the minting side — but no test in
   this repo mints a real token in one process and verifies it as Service Desk in another.
   Doing that would need two live servers and is a bigger lift than a seam fix; flagging it
   rather than skipping it silently.
3. **The `GET /api/agent/org/chain` ↔ `servicedesk/app/org_chart.py::HttpOrgChartClient`
   round trip was verified on each side independently** (MM OS's endpoint via
   `backend/tests/test_b1_seams.py`; Service Desk's client by code inspection and the URL/
   shape match), **not with both processes actually running against each other.** Same
   reasoning as item 2 — a genuine two-process integration test is out of reach without a
   deployed MM OS, and is a bigger lift than this pass's scope.
4. **The reconciled admin frontend pages (People/Access/Services-registry/LLM/Audit) were
   verified by `tsc --noEmit` + `npm run build` and by the backend-side shape tests, not by
   opening them in a browser against a live backend.** No Google OIDC credentials exist in
   this sandbox (standing sprint limitation, same one A1/A3 hit) to actually sign in as an
   admin through the real app end to end; A3's own mock-based manual verification already
   covers the same components' rendering logic against the shapes `contract.ts` declares,
   which are now what the real backend serves via `client.ts`'s adapter.
5. **`PATCH /api/admin/employees/{id}`'s response still doesn't carry the joined
   `user_id`/`auth_type`/`is_active`/`is_platform_admin`/`last_login_at` fields** — those live
   on `User`, not `Employee`, and the route only touches `Employee`. `client.ts`'s
   `updateEmployee` passes the response through unchanged. Not a regression (it was already
   this way), just not fixed either — it wasn't named in the seam inventory and fixing it
   would mean either a second fetch inside `client.ts` or extending `people.py`'s route
   itself; left as a minor, pre-existing gap rather than scope creep.
6. Everything named in seam inventory **section C** (pending access requests on the Access
   page, a user's own session list / true sign-out-everywhere, a `target_id` filter on
   `GET /api/admin/audit`, base-image CVE bumps, `login_email`/`google_sub` immutability,
   notifying a non-actor by email) — explicitly deferred by the orchestrator, not attempted.

## How to verify

All commands from the repo root unless noted; `PY` below is
`backend/.venv/Scripts/python.exe` (never bare `python`, per the standing instruction).

```bash
# One-time, if starting from a fresh checkout: make mmos-client-py importable for
# servicedesk's "http" auth mode (first-party code, not a new external dependency).
backend/.venv/Scripts/python.exe -m pip install -e packages/mmos-client-py --no-deps

# The four suites
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q          # 72 passed, 1 skipped
cd .. && backend/.venv/Scripts/python.exe -m pytest servicedesk -q  # 31 passed
backend/.venv/Scripts/python.exe -m pytest packages/mmos-client-py/tests -q  # 15 passed
node packages/embed/test/smoke.js                                   # 5 checks pass

# Both frontend builds
cd frontend && npx tsc --noEmit && npm run build && cd ..
cd servicedesk/frontend && npm run build && cd ../..

# The acceptance script itself (this is the actual deliverable)
bash scripts/verify/acceptance.sh local     # everything provable here
bash scripts/verify/acceptance.sh full      # same, plus Docker/Postgres checks (SKIP here)
```

## Acceptance results

Verbatim, `bash scripts/verify/acceptance.sh local`, run on this machine:

```
== MM OS acceptance -- mode: local ==

-- local checks --
PASS  backend/tests (60+ tests, 1 needs_postgres skip expected inside the suite)
PASS  servicedesk/tests (31 tests)
PASS  packages/mmos-client-py/tests (15 tests)
PASS  packages/embed/test/smoke.js (5 checks)
PASS  token mint + verify: RS256, JWKS, deny-list, alg-confusion (backend/tests/test_security.py)
PASS  grant removal appears on GET /api/agent/revocations immediately (backend/tests/test_platform.py)
PASS  client library rejects a revoked subject within one poll (packages/mmos-client-py)
PASS  B1 seams: error envelope, public services, org-chain, admin shape drift (backend/tests/test_b1_seams.py)
PASS  frontend: tsc --noEmit
PASS  frontend: npm run build
PASS  servicedesk/frontend: npm run build
PASS  seed dry-run against the real spreadsheet (73 employees, nothing written)

-- full-mode checks (Docker host / VPS only) --
SKIP  docker image build (deploy/Dockerfile) -- full mode not requested -- run 'scripts/verify/acceptance.sh full' on a Docker host
SKIP  docker compose up (deploy/docker-compose.yml) -- full mode not requested
SKIP  alembic upgrade head against real Postgres -- full mode not requested
SKIP  GET /healthz returns {"ok":true,"db":"up"} -- full mode not requested
SKIP  GET /.well-known/jwks.json returns an RSA key -- full mode not requested

== 12 passed, 0 failed, 5 skipped ==
```

`bash scripts/verify/acceptance.sh full` on this same (Docker-less) machine produces the
identical 12 PASS lines, then the five full-mode checks as `SKIP  ... -- docker is not
installed on this host` instead — confirming the script tells the truth about what it can
and cannot prove here, in both modes.

Final tallies at handoff (re-run standalone, matching the script's own numbers):

| Suite | Result |
|---|---|
| `backend/tests` | 72 passed, 1 skipped (`needs_postgres`) |
| `servicedesk/tests` | 31 passed |
| `packages/mmos-client-py/tests` | 15 passed |
| `packages/embed/test/smoke.js` | 5 passed |
| `frontend` | `tsc --noEmit` exit 0, `npm run build` OK |
| `servicedesk/frontend` | `npm run build` OK |

## Deferred ideas

- A real, per-endpoint service ACL (so `GET /api/agent/org/chain` could be restricted to the
  Service Desk service key specifically) rather than the current "any valid service key"
  trust boundary every service-authenticated MM OS endpoint already shares.
- `client.ts`'s `updateEmployee`/`listEmployees` join could move server-side (a real joined
  `/api/admin/people` endpoint) instead of two client-side fetches — reasonable, but a new
  endpoint is a feature, not a seam fix, so left for a future pass.
- A two-process integration test harness (spin up MM OS and Service Desk together, mint a
  real token in one, verify it in the other) would close the two "verified independently,
  not together" gaps in `## Not done` #2 and #3 properly. Worth having before the real
  cutover, not worth inventing during an assembly pass.
