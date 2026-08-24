# 08 · v1 scope and build plan

**v1 = shell + identity + Service Desk, thinned.** Both halves ship together so employees get
a reason to open MM OS on day one, not just a menu. Everything below is either in v1 or
explicitly deferred — nothing is left ambiguous, because ambiguous scope is what turns six
weeks into six months.

## In v1

**Shell and identity**
- Google OIDC login (`hd=m-mines.com`, MFA enforced in Workspace) + employee-code/PIN fallback
- 74 employees imported from the spreadsheet; MM OS is the master
- service registry with roles, health dot, launch mode
- `user × service × role` grants, admin UI, bulk grant by band or department
- tile homepage filtered by grants; search across tiles
- `embed.js` OS bar: back to MM OS, app switcher, ticket badge, identity
- RS256 JWT mint, JWKS, deny-list, `mmos-client-py`
- SSO retrofit on **ATT Platform** and **Item Code Studio** — the proof the model works on real services
- LLM control plane: registrations, usage, per-service kill switch
- audit log with a queryable admin view
- PWA manifest so MM OS installs as a window
- private-network enforcement (`NETWORK_MODE=private`)

**Service Desk**
- support tickets and automation requests
- full automation state machine with computed approver from the org chart
- IT proposal with resources and required `alternatives`
- comment thread, append-only event log
- email notification via Workspace SMTP
- my-requests, department view, IT queue

## Deferred, by decision

| Deferred | Lands in | Why now-is-wrong |
|---|---|---|
| Unified mail inbox (Gmail API) | v2 | Big surface; designed once alongside email-to-ticket intake |
| Cross-service global search | v2 | Needs a search contract in each service; the registry makes it possible later |
| SLA timers and escalation | v2 | Meaningless before there is baseline data on real response times |
| Email-to-ticket intake | v2 | Pairs with the inbox work |
| LLM cost dashboards and budgets | v2 | Needs a few months of `llm_usage_daily` first |
| ERPNext reconciliation report | v2 | Drift is slow; v1 has bigger risks |
| Mobile-specific layouts | v2 | Responsive is in v1; native-feel is not |
| Twenty CRM deep integration | v3 | Tile plus Google auth is enough for now |

## Milestones

**M0 · Foundations (week 1)**
Repo, Postgres on Coolify, container that builds and deploys, `/healthz`, CI, `.env` contract,
WireGuard up, split-horizon DNS, DNS-01 certificate for `os.m-mines.com`.
*Done when:* a hello-world MM OS is reachable over the VPN on a valid HTTPS certificate and
unreachable from a phone on mobile data.

**M1 · Identity (week 2)**
Schema and migrations, spreadsheet importer with dry-run diff, Google OIDC, PIN login,
sessions, `/api/me`, admin employees and users.
*Done when:* all 74 employees exist, three real people log in with Google, one operator logs
in with a PIN, and a deactivated user is refused.

**M2 · Tokens and the contract (week 3)**
Keypair and JWKS, `POST /api/token/service`, deny-list, `mmos-client-py` with a test service,
audit log.
*Done when:* the integration checklist in `05` passes end to end against a throwaway service,
including a token minted for the wrong `aud` being rejected and a removed grant taking effect
inside 60 seconds.

**M3 · The shell (weeks 4–5)**
React app: login, tile homepage, service launch, profile. Admin: services, roles, grants
(with bulk), audit view, LLM panel. `embed.js` in a shadow root with the app switcher. PWA
manifest.
*Done when:* someone with two grants sees exactly two tiles, opens both, and returns via the
bar without a second login.

**M4 · Retrofit the real services (week 6)**
ATT Platform and Item Code Studio adopt `mmos-client-py`, drop their PIN gates, add the
script tag. Item Code Studio gets the three dual-mode rules, including the read-only
Postgres role. ERPNext navbar back-link. ERPNext and Twenty tiles registered.
*Done when:* the PIN gate is deleted from both codebases and the public item-code lookup
still works anonymously while creation requires an `admin` grant.

**M5 · Service Desk (weeks 7–9)**
Separate repo and container. Both flows, approver computation, proposals, decisions, events,
email, the three views, MM OS badge.
*Done when:* a real automation request goes from an operator, through IT, to a HOD approval,
and the approval snapshot is immutable.

**M6 · Cutover (week 10)**
Grant review evening (the ERP-access column translated into real grants, ticked by a human),
PIN issue for non-mailbox staff, VPN peers for everyone, 30-minute floor training, MM OS set
as the browser homepage on office machines, backup restore test.
*Done when:* a week passes with no one using a bookmarked service URL directly.

Ten weeks for one developer working steadily. M0 and M1 are the ones that slip, because DNS,
certificates and the Google console are where the surprises live — do them first and in that
order.

## Definition of done for v1

1. Every employee logs in once and sees only what they are granted.
2. Every service in the registry is reached through MM OS, and each verifies tokens.
3. Removing a grant removes access within 60 seconds, provably.
4. An automation request completes the full approval chain and produces an immutable snapshot.
5. The LLM panel shows every AI-using service, and the kill switch demonstrably stops calls.
6. `audit_log` answers "who granted what, to whom, when" for the whole period.
7. Nothing is reachable from the public internet.
8. A restore from backup has been performed into a scratch database and verified.

## First five tasks, in order

1. `deploy/` — Dockerfile, compose, `.env.example`, Coolify app, Postgres with `pgcrypto`
2. `backend/app/models.py` + migration from the DDL in `02-data-model.md`
3. `backend/app/seed.py` — spreadsheet importer with dry-run diff
4. Google Cloud console: OAuth client, redirect URI, `hd` restriction; then `routers/auth.py`
5. `security.py` — keypair, JWKS, mint, verify, deny-list — and its tests, written first

Task 5 has tests written before the implementation. It is the one component where a subtle
bug is a silent security hole rather than a visible failure.
