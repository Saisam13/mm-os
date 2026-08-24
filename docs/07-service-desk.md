# 07 · Service Desk

Its own repo, own container, own Postgres database (`servicedesk`), own subdomain
(`desk.m-mines.com`). It joins MM OS through the same contract as every other service. It is
**not** part of the MM OS codebase — putting it there would make MM OS a monolith and defeat
the whole design.

It serves every service, including ERPNext and Twenty, which is exactly why it cannot live
inside any one of them.

## Two request types, deliberately different

| | **Support ticket** | **Automation request** |
|---|---|---|
| Means | something is broken or I need help | I want something built or automated |
| Raised by | anyone | anyone |
| Path | IT triage → work → resolve | IT proposal → manager approval → build → deploy |
| Needs money or servers | no | yes — that is why it needs approval |
| Ends as | a fix | a new service, or a feature in an existing one |

The second flow is why this is custom-built. No off-the-shelf helpdesk models *IT proposes
scope and resources, then the requester's department manager approves the cost*. Zammad can
run a support queue beautifully and cannot do this at all.

## State machines

**Support**

```
open ──▶ in_progress ──▶ waiting_on_requester ──▶ resolved ──▶ closed
   └──────────────▶ rejected (with reason)          ▲
                                                    └── reopened within 7 days
```

**Automation request**

```
draft
  └▶ submitted ──▶ it_review ──▶ proposal_ready ──▶ manager_review ──┬▶ approved ──▶ in_build ──▶ deployed ──▶ closed
                       │              ▲                             ├▶ changes_requested ──┐
                       │              └─────────────────────────────┘                      │
                       └▶ rejected (IT: not feasible)                └▶ rejected (manager: not funded)
```

Rules the machine enforces, not the humans:

- `submitted → it_review` cannot be skipped: a request with no IT proposal cannot reach a manager, so managers are never asked to approve something with no scope or cost attached
- the approver is computed, not chosen: `employees.manager_id` of the requester, escalating up bands until someone with a qualifying `approval_level` is found; `is_approver` overrides from the sheet are honoured
- a requester can never approve their own request, even if they are the computed approver — it escalates one level
- `approved` writes an immutable snapshot of exactly what was approved (scope, effort, resources), so later scope growth is visible rather than assumed

## The proposal — where resource allocation becomes real

IT fills this in during `it_review`:

```json
{
  "scope_summary": "Nightly job pulls DPR from ERPNext, flags variance beyond 5%, mails P-Spoke HOD.",
  "effort_days": 4,
  "resources": {
    "new_service": true,
    "container": { "cpu": "0.5", "ram_mb": 512 },
    "database": "postgres/dpr_watch",
    "llm": { "needed": true, "provider": "anthropic", "est_monthly_tokens": 400000 }
  },
  "risks": "Depends on Frappe Cloud API rate limits.",
  "alternatives": "An ERPNext report and a saved filter, at zero build cost."
}
```

`alternatives` is a required field. It is the cheapest way to stop the department building a
service that a report would have solved, and it makes the manager approval a real choice
rather than a rubber stamp.

`resources.llm` is what closes the loop with the MM OS control plane: an approval says how
much a service is expected to consume, and the LLM admin page shows what it actually
consumed. The gap between those two numbers is the interesting number.

## Schema (database `servicedesk`)

```sql
CREATE TABLE tickets (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ref               text NOT NULL UNIQUE,          -- SD-2026-0142 / AR-2026-0031
    kind              text NOT NULL CHECK (kind IN ('support','automation')),
    title             text NOT NULL,
    body              text NOT NULL,
    requester_sub     text NOT NULL,                 -- "user:<uuid>" from the MM OS token
    requester_code    text NOT NULL,                 -- MM32, denormalised for reporting
    requester_dept    text NOT NULL,
    service_slug      text,                          -- which service it concerns, if any
    priority          text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
    is_private        boolean NOT NULL DEFAULT false, -- hides title/body/comments from the department queue
    status            text NOT NULL,
    assignee_sub      text,
    approver_sub      text,                          -- computed at submit time
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    first_response_at timestamptz,
    closed_at         timestamptz
);
CREATE INDEX ON tickets (status, kind);
CREATE INDEX ON tickets (requester_sub);

CREATE TABLE proposals (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id     uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_sub    text NOT NULL,
    scope_summary text NOT NULL,
    effort_days   numeric(5,1),
    resources     jsonb NOT NULL DEFAULT '{}',
    risks         text,
    alternatives  text NOT NULL,
    version       int  NOT NULL DEFAULT 1,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ticket_id, version)
);

CREATE TABLE decisions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id    uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    proposal_id  uuid REFERENCES proposals(id) ON DELETE SET NULL,
    approver_sub text NOT NULL,
    approver_code text NOT NULL,
    decision     text NOT NULL CHECK (decision IN ('approved','rejected','changes_requested')),
    comment      text,
    snapshot     jsonb NOT NULL,                     -- immutable copy of what was approved
    decided_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE comments (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id   uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_sub  text NOT NULL,
    body        text NOT NULL,
    is_internal boolean NOT NULL DEFAULT false,      -- IT-only notes
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE events (                                -- append-only, the audit trail
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id  uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    actor_sub  text,
    from_status text,
    to_status   text,
    detail     jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
```

Note it stores `requester_sub` (the MM OS subject) and not a foreign key into MM OS — a
separate database means no cross-database joins. Names and departments are denormalised at
write time, and the OS bar resolves current names for display.

## Roles

| Role | Can |
|---|---|
| `requester` | default for everyone: raise, comment on and track their own tickets |
| `agent` | IT team: triage, assign, write proposals, resolve |
| `approver` | not granted in MM OS — computed per ticket from `manager_id` and `approval_level` |
| `admin` | categories, SLA config, reassignment, reopen closed tickets |

Only `agent` and `admin` are MM OS grants. Approval authority comes from the org chart, so
granting it as a service role would create a second, conflicting source of truth.

## Who can see what — decided 23 Aug 2026

Everyone in a department sees **every request that department raised**, including who it is
assigned to and how long it has waited. Transparency was chosen over privacy here: it stops
duplicate tickets and it lets a requester see their request has not been forgotten.

The exception is the `is_private` flag a requester may set. It restricts title, body and
comments to three people: the requester, the assignee and the computed approver. The request
still appears in the department queue as a **hidden row** — age and assignee only — so the
queue count stays honest and nothing disappears silently.

Two rules on this, both of which are the kind of thing that gets got wrong:

- **Filter in the query, not in the browser.** A hidden row must never have its title sent to
  a client that merely styles it away. Assume someone will open the network tab.
- The flag is opt-in, so it will be forgotten exactly when it matters most. Put the choice on
  the request form where it is visible, not behind an advanced section, and let IT set it
  after the fact on a request that should have had it.

## In v1, and not in v1

**In:** both request types, the full automation state machine, computed approver, proposal
with resources, comment thread, event log, email notification via Workspace SMTP, my-requests
and queue views, MM OS badge count.

**Out (v2):** SLA timers and escalation, email-to-ticket intake, knowledge base, CSAT,
recurring requests, the unified inbox. Email intake in particular waits for the Gmail inbox
work so both get designed once, properly.

Until intake exists, people will still email IT directly. Accept that; the answer is a link
in the mail signature, not a policy memo.
