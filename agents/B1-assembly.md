# Agent B1 · Assembly and acceptance

Six agents built **MM OS** — the internal operating system for MiniMines (~74 staff) — in
parallel on six branches. Your job is to make them one working system. You add no features.

**Read first:** every file in `handoff/` — that is where the six agents recorded what they
actually built, where they deviated, and what they assumed. Then `docs/09-build-agents.md`
(ownership and merge order) and `docs/08-v1-plan.md` (the definition of done you are proving).

## Merge in this order

```
a6-infra → a1-identity → a2-tokens → a4-kit → a3-shell → a5-desk
```

Infra first so there is something to run against; identity before tokens because the single
Alembic migration lands with A1; the shell late because it is the most likely to need a tweak
once the API is real.

Conflicts should be near zero — ownership was exclusive. **Any conflict is a brief violation,
not a puzzle to solve creatively:** record it in `handoff/b1-assembly.md` under
`## Ownership violations`, take the version that matches `docs/03-api-contract.md`, and move
on.

## What you do

1. **Merge and make it boot.** `docker compose up`, migrations applied, `/healthz` green,
   frontend served from the same port, `embed.js` served.

2. **Reconcile the seams.** These are where six parallel agents will actually have diverged:
   - `/api/me` payload versus what the shell consumes — the doc is the referee
   - error envelope shape (`{error, message, request_id}`) used consistently by all routers
   - the client library's verification order versus what `security.py` actually mints
   - cookie domain and CORS between MM OS, echo-service and Service Desk on different subdomains
   - `poll_after_seconds` and heartbeat intervals agreeing between A2 and A4
   - the Service Desk badge count reaching `/api/me` (A1 left it hardcoded to 0 — wire it)

3. **Resolve every `## Contract objections` entry.** Each is a claim that a frozen file is
   wrong. For each: fix it in the frozen file **now** (you are the only agent permitted to),
   or write down why it stands. Do not leave one unanswered.

4. **Write `scripts/verify/acceptance.sh`** — one runnable script proving the eight v1
   criteria in `docs/08-v1-plan.md`, printing a pass/fail line each. This script is the
   deliverable that outlives you; it is how every future change gets checked.
   It must cover, end to end against running containers:
   - Google login stub and PIN login both produce a session
   - `/api/me` returns only granted services
   - a token minted for `itemcode` is rejected by `echo-service`
   - removing a grant blocks echo-service inside 60 seconds
   - MM OS stopped: echo-service still serves an already-authenticated user
   - LLM toggled off: the echo LLM route returns 503 within one heartbeat
   - an automation request completes the approval chain and its snapshot is immutable
   - with `NETWORK_MODE=private` and the caller outside the CIDR list, everything except `/healthz` and the JWKS returns 403

5. **Fix what the script catches** — but only what it catches. A found bug is in scope; an
   improvement you thought of is not. Note improvements under `## Deferred ideas`.

## Guardrails

No new features. No refactoring beyond what a failing acceptance check demands. Do not
redesign an interface because you would have done it differently — if it works and matches the
doc, leave it. No new dependencies. If a failure resists two fixes, record it under
`## Not done` with what it blocks and move on; a documented gap is worth more than a rushed
patch to a security path.

## Finish by writing `handoff/b1-assembly.md`

`## Merged` (branch, commit, notes) · `## Ownership violations` · `## Contract objections
resolved` (each, with the decision) · `## Seams fixed` · `## Acceptance results` (the script
output, verbatim) · `## Not done` · `## Deferred ideas`.
