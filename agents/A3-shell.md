# Agent A3 · The shell frontend

You are building the face of **MM OS**, the internal operating system for MiniMines
(lithium-ion battery recycling, ~74 staff). It is the homepage every employee opens: one
login, tiles for the services they are allowed to use, and the admin console IT runs it from.
You are one of six agents building in parallel.

**Read first, and in this order:**

1. `brand/UI-DECISIONS.md` — every UI decision the brand owner has locked. Not negotiable, and it answers most questions you will have.
2. `brand/BRAND.md` — the measured MiniMines palette and typefaces. Petrol `#005D7F` leads, navy `#002060` grounds the chrome, orange `#FF6A00` is **action only**, Roboto + Roboto Condensed.
3. `demo/console-directions.html` — the approved clickable prototype and the **visual source of truth**: palette, type, spacing, component shapes, copy tone. Reproduce the selected direction in React; do not redesign it.
4. `docs/03-api-contract.md` for every API shape, `docs/01-architecture.md` for what the product is.

`demo/_superseded-first-prototype.html` is retired — it used a placeholder palette. Ignore it.

**The direction is chosen: B — top nav, calm.** The prototype carries three, switchable by
the picker at the bottom; build **only B**, the `[data-dir="b"]` branch. In the prototype that
is the `.topnav` header and its `.topnav-i` items — a 60px navy sticky bar with the logo
lockup, then Services · Service Desk · Access · AI services as flat text buttons (selected one
white with a 3px petrol underline), a spacer, Search, and the avatar chip. **No left rail** —
ignore `.rail*` and `.cmdtop*` entirely. Keep the command palette; in B it is reached from the
Search button and `CTRL K`. `brand/UI-DECISIONS.md` § Console direction is the record.

## You own exclusively

```
frontend/**
```

Nothing else. The backend is being built in parallel by A1 and A2 against the same documented
contract — do not create backend files, and do not change the API shapes to suit the UI. If a
shape is wrong, note it in your handoff.

## Stack — match the house pattern, do not introduce a new one

React 18 + TypeScript + Vite + React Router 6, as in `ATT_Platform/frontend`. Plain CSS with
custom properties (the demo already defines the token set — lift it verbatim into
`src/styles/tokens.css`). **No** Tailwind, no component library, no state management library;
`fetch` and React context are enough for this size of app.

Build output goes to `frontend/dist`, which `backend/app/main.py` already serves — one
container, one port, the pattern that already works here.

## Deliverables

1. **Entry page — one page.** Logo lockup, the Google button
   (`/api/auth/google/start`), the employee-code + PIN form for staff without mailboxes, and
   underneath a **public list of every service**, visible before sign-in. Clicking a service
   there goes straight to it: in-house services bounce to MM OS and come back with a token;
   ERPNext and Twenty open their own sign-in on the same Google accounts. Show real errors:
   locked account, unknown user, wrong network. An `AuthProvider` fetching `/api/me` once and
   holding it in context; a 401 anywhere returns the user here.

   The public list needs a server endpoint that returns names and launch URLs **only** — no
   roles, no health, no internal detail. If `docs/03-api-contract.md` has no such endpoint,
   note it in your handoff; do not reuse `/api/me`, which requires a session.

2. **Services list** — the same surface after sign-in, now with each person's role and status
   filled in. Rows, **not** icon tiles, each with a mark: real logo for third-party services
   (`brand/service-marks/`, falling back to a tile in the service's brand colour with its
   initial), Roboto Condensed initials on petrol for in-house ones — `ICS`, `ATT`, `SD`, `AH`,
   derived from the name so a new service is never missing a mark. **No generic line icons.**
   Rows come from `/api/me`; **never filter client-side**, the server already returned only
   what the user may open. Clicking calls `POST /api/token/service` and navigates to the
   returned `launch_url` — show progress while minting, and a real error if the grant was
   removed in the meantime. Cmd/Ctrl-K opens the command palette.

3. **Admin** (only when `user.is_platform_admin`)
   - **People** — searchable employee table, filter by department and status, drawer to edit,
     PIN issue and reset, deactivate with a confirmation that states plainly what it does
     ("Ends every session and removes access to 4 services within 60 seconds").
   - **Access** — the core screen, and it carries four things, all in v1:
     (a) a matrix of people against services where a cell is empty or holds a role chip, with
     bulk grant by band or department;
     (b) **per-person drill-down** — click a row for a panel listing every service, the role
     held, who granted it, when, and why;
     (c) **role meanings inline** — what `admin` actually permits on that service, read from
     the service's declared role descriptions, shown where the grant is made so nobody grants
     a role by guessing at its name;
     (d) **expiry dates and change history** per grant, and **pending access requests decided
     in place** on this page, fed from Service Desk.
     Every destructive action confirms once, never twice.
   - **Services** — registry CRUD, roles per service, rotate key (show the key once, with a
     copy button and an explicit "you will not see this again").
   - **LLM** — one row per service: provider, model, key present, enabled toggle, 30-day
     token usage sparkline, last seen. A service that has not reported shows `unreported` in
     a muted style, not blank. The toggle asks for a reason.
   - **Audit** — filterable log, actor, action, target, time, IP.

4. **Profile** — who you are, your department, band, approval level, your services and roles,
   your active sessions with a sign-out-everywhere button.

5. **PWA** — `manifest.webmanifest` and icons so MM OS installs as a window on office
   machines. No service worker caching of API responses; offline is not a goal and a stale
   permission cache is a hazard.

6. **`frontend/README.md`** — how to run, how to point at a local API, where the tokens live.

## Rules that matter more than they look

- **Every list is empty before it is full.** Design the empty state for tiles ("No services
  yet — raise a request and IT will set you up"), grants, audit, and LLM. An employee with no
  grants must not see a broken page.
- **Never show a service the API did not return.** Tiles are not hardcoded anywhere.
- **No marketing copy. Anywhere.** No greetings, no "five services are open to you", no
  "anything missing is a request away", no "all services healthy". The brand owner removed
  these from the first prototype specifically; do not reintroduce them in any form. Headings
  name a page, they do not sell it. Labels and data only.
- **Copy is written from the user's side.** "You cannot open this yet" not
  "403 grant_not_found". Errors say what happened and what to do.
- **Both themes work.** The demo defines light and dark tokens; keep the token discipline and
  never hardcode a colour in a component.
- Keyboard focus is always visible. The whole tile grid is navigable without a mouse — plant
  staff use shared terminals with poor trackpads.
- Tabular numbers for every column of digits.

## Development without a backend

A1 and A2 are building the API right now, so develop against a mock: `src/api/mock.ts`
returning the exact payloads from `docs/03-api-contract.md`, toggled by
`VITE_USE_MOCK=true`. Keep the real client in `src/api/client.ts` and make the mock a
drop-in. **The mock must not survive into the production build path** — one flag, checked in
one place.

## Acceptance

- a user with two grants sees exactly two tiles; a user with none sees the empty state
- clicking a tile mints a token and navigates; a revoked grant shows a real error, not a crash
- admin screens are unreachable and invisible for a non-admin
- the LLM toggle round-trips and shows `unreported` correctly
- it looks like `demo/index.html` — a colleague should not be able to tell them apart
- light and dark both readable; no hardcoded colours outside `tokens.css`

## Guardrails

Do not refactor anything outside `frontend/`. No new dependencies beyond React, Router,
Vite and TypeScript without recording it in the handoff. No UI kit. No test framework setup
unless you use it. If a failure resists two fixes, write it under `Not done` and move on.

## Finish by writing `handoff/a3-shell.md`

`## Delivered`, `## Deviations`, `## Contract objections`, `## Assumptions`, `## Not done`,
`## How to verify`.
