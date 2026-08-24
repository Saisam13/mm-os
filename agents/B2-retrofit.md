# Agent B2 · Retrofit the existing services

**MM OS** now works (agent B1 assembled it). Your job is to move MiniMines' two existing
in-house services onto it and delete their old authentication. This is the run where MM OS
stops being a menu and starts being the front door.

You are working across **three repositories**:

```
C:/Users/Anura/OneDrive/Desktop/MM OS          (reference only — do not modify)
C:/Users/Anura/OneDrive/Desktop/ATT_Platform   (modify)
C:/Users/Anura/OneDrive/Desktop/…/Item Code Studio  (modify — locate it first)
```

**Read first:** `MM OS/docs/05-service-integration.md` — the contract and the integration
checklist you must tick. Then `MM OS/packages/mmos-client-py/README.md` and
`MM OS/examples/echo-service` — a working reference implementation of exactly what you are
about to do twice.

**Commit to a branch in each repo, never to `main`, and never force-push.** These are working
tools people use; a broken deploy costs a day of someone's real work.

## Before you change anything

1. Locate Item Code Studio. It was not in the MM OS scan — check the Desktop folders, and if
   it is not on disk, **stop, record that in your handoff, and do ATT only.** Do not invent it.
2. Confirm both services run locally first. A retrofit onto something you have never seen
   working is guesswork.
3. Note each service's current auth. `ATT_Platform/backend/main.py` has an optional shared-PIN
   gate (`pin_gate` middleware, `/api/auth/verify`, `settings.pin_enabled`). That is what you
   are replacing.

## ATT Platform (FastAPI + Vite/React, single port, SQLite)

1. Register it in MM OS admin as slug `att` with roles `viewer` and `runner`; take the service
   key once and put it in the service's environment.
2. Add `mmos-client-py`, mount it with `public_paths=[]` — ATT has no public surface.
3. Guard the routes: read-only endpoints require any role; anything that starts a run,
   uploads a portfolio, edits settings or touches the LLM requires `runner`.
4. **Delete the PIN gate** — the middleware, `/api/auth/verify`, the settings keys, and the
   PIN entry screen in the frontend. Leaving it as a second door defeats the point. Remove it,
   do not comment it out.
5. It already has LLM settings (`backend/llm.py`, provider and key in service settings). Wire
   `llm_guard()` into the matcher entry point and `report_usage()` where the provider returns
   token counts. **Keys stay exactly where they are** — MM OS never receives one.
6. Add `<script src="https://os.m-mines.com/embed.js" defer></script>` to `frontend/index.html`.

## Item Code Studio (dual-mode: public lookup plus admin console)

This is the risky one: one app serving an anonymous public surface and item-code creation.
Apply all three structural rules from `docs/05-service-integration.md` — not two of them.

1. **One prefix for writes.** Every mutating endpoint moves under `/api/admin/*` behind a
   single guard. After your change there must be **no** mutating endpoint anywhere else, so a
   future route cannot be born unprotected.
2. **The anonymous surface is an allowlist.** `public_paths` enumerates the public lookup and
   nothing more. Anything unlisted requires a token, so a forgotten route fails closed.
3. **The public surface reads through a read-only Postgres role** (`deploy/postgres/init.sql`
   from agent A6 creates it). Two connection strings: read-only for public paths,
   read-write for `/api/admin/*`. This is the rule that still protects you when rules 1 and 2
   are broken by a future edit — do not skip it because the other two feel sufficient.
4. Roles: `viewer` (read the admin console) and `admin` (create and edit item codes).
5. Add the `embed.js` tag. Verify the public page renders **without** the bar breaking for an
   anonymous visitor — the bar must degrade to a plain link, not error.

## ERPNext and Twenty CRM (no code, configuration only)

- **ERPNext** (Frappe Cloud, `minimines-uat.m.frappe.cloud`): document the steps to enable
  Google social login against the same Workspace, and add a **Back to MM OS** entry via
  **Navbar Settings → custom navbar items**. Write the click-path in
  `handoff/b2-retrofit.md`. **Do not make changes to the live instance** — it is production
  ERP. Document, and let a human apply it.
- **Twenty CRM**: register the tile in MM OS, note where the `embed.js` tag goes in its build.

## Acceptance — tick the full checklist in `docs/05-service-integration.md` for each service

Plus, specifically:

- a token minted for `att` is rejected by Item Code Studio and vice versa
- the public item-code lookup works with **no** session at all
- creating an item code without an `admin` grant returns 403
- the public path cannot write even when pointed at a write query (prove the read-only role holds)
- both PIN gates are gone from both codebases (grep for `pin` and show the result)
- both appear in `/api/admin/llm` with real usage, or as `unreported` deliberately
- the OS bar renders in both and back-to-MM-OS works

## Guardrails

Branch per repo, no force-push, no `main`. Do not refactor these services beyond what the
retrofit needs — you are threading auth through, not modernising them. Do not change their
databases beyond the connection-role split. Do not touch the live ERPNext instance. If a
service will not run locally, say so and skip it rather than editing blind.

## Finish by writing `MM OS/handoff/b2-retrofit.md`

`## Delivered` (per service, with branch names) · `## ERPNext steps for a human` ·
`## Deviations` · `## Assumptions` · `## Not done` · `## How to verify`.
