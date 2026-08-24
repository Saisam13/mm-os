# Agent A5 · Service Desk

You are building the Service Desk for **MiniMines** (lithium-ion battery recycling, ~74
staff): the one place anyone raises a support ticket or requests an automation, covering every
company system including ERPNext and Twenty CRM. It is a **separate service** — its own
directory, container, database and subdomain — that joins MM OS through the standard
integration contract. You are one of six agents building in parallel.

**Read first:** `docs/07-service-desk.md` — the complete specification, including both state
machines, the schema and the approval rules. Then `docs/05-service-integration.md` (how you
join MM OS) and `demo/index.html` (visual language — reuse its tokens).

## You own exclusively

```
servicedesk/**
```

Nothing outside it. Do not add tables to the MM OS database; you own database `servicedesk`
and its own migrations. Cross-database joins do not exist here — you store `requester_sub`
(the MM OS subject string) and denormalise names and departments at write time.

## Stack

FastAPI + SQLAlchemy + Alembic + Postgres, and a Vite/React frontend served by the same
container on one port — the same pattern as MM OS itself. Auth comes from
`packages/mmos-client-py` (agent A4 is writing it in parallel; code against the interface
documented in `docs/05-service-integration.md` and stub it locally if it is not yet
importable — say so in your handoff).

## Deliverables

1. **Schema and migrations** — `tickets`, `proposals`, `decisions`, `comments`, `events`
   exactly as in `docs/07-service-desk.md`. `events` is append-only; never update or delete a
   row in it.

2. **Both state machines, enforced in code, not by convention** — the transition tables are
   in `docs/07`. Illegal transitions return `409 invalid_transition` naming the current and
   attempted state. Every transition writes an `events` row with actor, from, to.

3. **The rules that make approval real** — these are the point of the service:
   - `submitted → it_review` cannot be skipped: a request with no proposal can never reach a
     manager, so nobody is ever asked to approve an unscoped, uncosted request
   - the approver is **computed, not chosen**: walk `manager_id` up from the requester until
     someone with a qualifying `approval_level` is found; honour `is_approver` overrides. Read
     the org chart from MM OS via `GET /api/me` claims plus an approver-lookup call; if MM OS
     does not expose what you need, note it in the handoff rather than duplicating the org
     chart in your database.
   - a requester can never approve their own request even when they are the computed
     approver — it escalates one level
   - `approved` writes an **immutable snapshot** of exactly what was approved into
     `decisions.snapshot`, so later scope growth is visible rather than assumed
   - `proposals.alternatives` is a **required** field — it is the cheapest way to stop a
     department building a service that a saved report would have solved

4. **API** — REST under `/api`: create ticket, list mine, list by department, IT queue,
   transition, comment (with `is_internal` for IT-only notes), create and revise proposal
   (versioned), decide. Roles from the MM OS token: `requester` (default for everyone),
   `agent` (IT), `admin`. `approver` is **not** a granted role — approval authority comes from
   the org chart, and granting it in MM OS would create a second conflicting source of truth.

5. **Frontend — four views**, confirmed by the brand owner, plus the request form and the
   detail page. Visual language and tokens come from `demo/console-directions.html` and
   `brand/UI-DECISIONS.md` (petrol leads, orange is action only, Roboto + Roboto Condensed,
   **no marketing copy**).

   | View | Who | Shows |
   |---|---|---|
   | My requests | everyone | what I raised, its state, what waits on me |
   | Department queue | everyone in the department | every request the department raised, **with assignee and age** |
   | IT agent console | `agent` | unassigned queue, triage, assign, write and revise proposals, resolve |
   | Approver decisions | computed approvers | requests awaiting their decision, with proposal, resources and cost in view, and approve / reject / request-changes in place |

   Plus: the request form (one form switching between support and automation) and the ticket
   detail page — thread, proposal, approval state, event history as a timeline.

   **Department queue privacy — enforce it server-side, never by hiding in the UI.** Everyone
   in a department sees every request it raised. A requester may mark one **private**, which
   restricts title, body and comments to the requester, the assignee and the computed
   approver. A private request still appears in the queue as a **hidden row** so the count
   stays honest — age and assignee only, no title, no detail. Filter those fields out of the
   query; do not send them to the browser and style them away.

6. **Notifications** — email via Workspace SMTP (`SMTP_*` in `deploy/.env.example`) on:
   submitted, proposal ready, decision, resolved. Template them in one module. A failed send
   must not fail the transition — queue and retry, and surface failures in the IT queue.

7. **MM OS integration** — mount the client library, expose `/_mmos/health`, send the
   heartbeat, include `<script src="https://os.m-mines.com/embed.js" defer>`, and expose
   `GET /api/badge?sub=...` returning the open count for the OS bar. Every write endpoint
   under `/api/admin/*` or guarded by an explicit role dependency.

8. **`servicedesk/README.md`** — run, migrate, seed, and the state diagrams copied in.

## Explicitly out of scope for v1

SLA timers, escalation, email-to-ticket intake, knowledge base, CSAT, recurring requests,
the unified inbox. Do not build them, do not stub them, do not leave `TODO` scaffolding for
them. They land in v2 alongside the Gmail inbox work.

## Acceptance

- an automation request goes operator → IT proposal → HOD approval → build → deployed, with an events row for each hop
- an attempt to jump `submitted → manager_review` returns 409
- a requester who is their own computed approver sees it escalate one level
- a proposal saved without `alternatives` is rejected
- the approval snapshot does not change when the proposal is later revised
- a support ticket runs open → in_progress → resolved → closed and can reopen inside 7 days
- the badge endpoint returns the right count and the OS bar shows it

## Guardrails

Do not refactor anything outside `servicedesk/`. Do not touch the MM OS database or backend.
No dependencies beyond the MM OS stack (FastAPI, SQLAlchemy, Alembic, psycopg, React, Vite).
Targeted tests on the state machines and the approver computation — that is where the bugs
will be. If a failure resists two fixes, write it under `Not done`. Never touch `.env`, real
secrets, or the live ERPNext instance.

## Finish by writing `handoff/a5-servicedesk.md`

`## Delivered`, `## Deviations`, `## Contract objections`, `## Assumptions`, `## Not done`,
`## How to verify`.
