# 02 · Data model

Postgres 16. One instance on the VPS, one database per service. MM OS uses database `mmos`.
All ids are `uuid` with `gen_random_uuid()` (`pgcrypto`). All timestamps are `timestamptz`.

MM OS stores four things and nothing else: **who works here**, **what services exist**,
**who may open which service in what role**, and **what happened**.

## Entity map

```
employees ──1:1── users ──┬── grants ──┬── services ──┬── service_roles
    │                     │            │              ├── llm_registrations
    │ manager_id          ├── sessions │              └── llm_usage_daily
    └─ self ref           └── revocations (deny-list)
                                                       audit_log (references everything)
```

## DDL

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── people ────────────────────────────────────────────────────────────────
CREATE TABLE employees (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_code   text NOT NULL UNIQUE,          -- MM01 … MM74
    full_name       text NOT NULL,
    work_email      text UNIQUE,                   -- null for shop-floor staff
    hr_department   text NOT NULL,                 -- P-Spoke, QA/QC, Purchase …
    division        text NOT NULL,                 -- Production, Finance, Corporate …
    job_title       text NOT NULL,
    band            text NOT NULL,                 -- L1, L1S, L2, L3, L4, L5, NON L
    approval_level  text,                          -- "L3 (HOD)", "L5 (Apex)", Operational
    manager_id      uuid REFERENCES employees(id) ON DELETE SET NULL,
    is_approver     boolean NOT NULL DEFAULT false,-- special approver override in the sheet
    notes           text,
    status          text NOT NULL DEFAULT 'active' -- active | suspended | exited
                    CHECK (status IN ('active','suspended','exited')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON employees (hr_department);
CREATE INDEX ON employees (manager_id);

CREATE TABLE users (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id       uuid NOT NULL UNIQUE REFERENCES employees(id) ON DELETE CASCADE,
    login_email       text UNIQUE,                 -- Google account, when they have one
    auth_type         text NOT NULL DEFAULT 'google'
                      CHECK (auth_type IN ('google','local_pin')),
    pin_hash          text,                        -- argon2id, only for local_pin
    pin_set_at        timestamptz,
    is_platform_admin boolean NOT NULL DEFAULT false,
    is_active         boolean NOT NULL DEFAULT true,
    last_login_at     timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pin_required CHECK (auth_type <> 'local_pin' OR pin_hash IS NOT NULL),
    CONSTRAINT email_required CHECK (auth_type <> 'google' OR login_email IS NOT NULL)
);

-- ── service registry ──────────────────────────────────────────────────────
CREATE TABLE services (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug               text NOT NULL UNIQUE,       -- itemcode, att, erpnext, servicedesk
    name               text NOT NULL,
    tagline            text,
    category           text NOT NULL DEFAULT 'internal',  -- erp | production | commercial | platform
    base_url           text NOT NULL,
    icon               text,                       -- lucide icon name
    launch_mode        text NOT NULL DEFAULT 'handoff'
                       CHECK (launch_mode IN ('handoff','embed','external')),
    has_public_surface boolean NOT NULL DEFAULT false,
    public_url         text,
    health_url         text,
    owner_employee_id  uuid REFERENCES employees(id) ON DELETE SET NULL,
    service_key_hash   text,                       -- sha256, for server-to-server calls
    is_active          boolean NOT NULL DEFAULT true,
    sort_order         int NOT NULL DEFAULT 100,
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE service_roles (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id  uuid NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    key         text NOT NULL,                     -- viewer | admin | runner | approver
    name        text NOT NULL,
    description text,
    is_default  boolean NOT NULL DEFAULT false,
    UNIQUE (service_id, key)
);

-- ── the permission model: one row = one person may open one service in one role ──
CREATE TABLE grants (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    service_id      uuid NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    service_role_id uuid NOT NULL REFERENCES service_roles(id) ON DELETE RESTRICT,
    granted_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    reason          text,
    expires_at      timestamptz,                   -- null = permanent
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, service_id)                   -- one role per service per person
);
CREATE INDEX ON grants (service_id);

-- ── sessions and revocation ───────────────────────────────────────────────
CREATE TABLE sessions (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token_hash text NOT NULL UNIQUE,
    ip                 inet,
    user_agent         text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    expires_at         timestamptz NOT NULL,
    revoked_at         timestamptz
);
CREATE INDEX ON sessions (user_id) WHERE revoked_at IS NULL;

-- Rows here are what services poll. Kept small: entries expire once no live
-- token could still carry the subject (revoked_at + token TTL + slack).
CREATE TABLE revocations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject     text NOT NULL,                     -- "user:<uuid>"
    service_id  uuid REFERENCES services(id) ON DELETE CASCADE,  -- null = all services
    jti         text,                              -- optional single-token kill
    reason      text NOT NULL,
    revoked_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    revoked_at  timestamptz NOT NULL DEFAULT now(),
    purge_after timestamptz NOT NULL DEFAULT (now() + interval '2 hours')
);
CREATE INDEX ON revocations (revoked_at);

-- ── LLM control plane (keys never live here) ──────────────────────────────
CREATE TABLE llm_registrations (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id   uuid NOT NULL UNIQUE REFERENCES services(id) ON DELETE CASCADE,
    provider     text,                             -- anthropic | openai | local | unreported
    model        text,
    key_present  boolean NOT NULL DEFAULT false,   -- reported by the service, never the key
    enabled      boolean NOT NULL DEFAULT true,    -- the kill switch MM OS owns
    disabled_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    disabled_at  timestamptz,
    last_seen_at timestamptz
);

CREATE TABLE llm_usage_daily (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id    uuid NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    day           date NOT NULL,
    requests      bigint NOT NULL DEFAULT 0,
    input_tokens  bigint NOT NULL DEFAULT 0,
    output_tokens bigint NOT NULL DEFAULT 0,
    UNIQUE (service_id, day)
);

-- ── audit ─────────────────────────────────────────────────────────────────
CREATE TABLE audit_log (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    action        text NOT NULL,     -- login.google, token.issue, grant.create, llm.disable …
    target_type   text,
    target_id     text,
    service_id    uuid REFERENCES services(id) ON DELETE SET NULL,
    ip            inet,
    metadata      jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_log (created_at DESC);
CREATE INDEX ON audit_log (actor_user_id, created_at DESC);
```

## Seeding from the employee sheet

Source: `Desktop/Erp Imp/Employee_Role_Access_Mapping.xlsx`, sheet
`Employee Role & Access Map` — 74 rows.

| Sheet column | Lands in |
|---|---|
| Employee Code | `employees.employee_code` |
| Full Name | `employees.full_name` |
| Work Email | `employees.work_email` and `users.login_email` |
| HR Department | `employees.hr_department` |
| Division (Approval Matrix) | `employees.division` |
| Job Title (New Org Structure) | `employees.job_title` |
| Band | `employees.band` |
| Approval Level | `employees.approval_level` |
| Special Approver Override | `employees.is_approver = true` + text into `notes` |
| ERP-Based System Access / Extra Report Access | **not imported as grants** — printed as a suggestion report for review |

That last row matters. The sheet describes ERP document permissions in prose
("Approve & review: Purchase Order…"). Machine-translating prose into access rights is how
you accidentally grant something. The importer prints a proposed grant list; a human ticks
it in the admin UI. One evening of work, once.

Rows with no `Work Email` become `auth_type = 'local_pin'` users with no PIN set — they
appear in admin as **PIN not set** until IT issues one.

## Retention

- `audit_log` — 24 months, then archive to cold storage
- `sessions` — deleted 30 days past expiry
- `revocations` — purged past `purge_after` by a background job (they only need to outlive live tokens)
- `llm_usage_daily` — kept indefinitely; it is tiny and it is the cost history
