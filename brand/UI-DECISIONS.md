# UI decisions — locked 23 Aug 2026

Confirmed by the brand owner after reviewing the first prototype. These override anything in
the retired `demo/_superseded-first-prototype.html`, which used a placeholder palette.

Visual source of truth: **`demo/console-directions.html`**. Brand values: **`brand/BRAND.md`**.

## Colour roles

| Role | Value | Used for |
|---|---|---|
| Primary | `#005D7F` petrol (logo ink) | Navigation, links, active and selected states, focus rings |
| Ground | `#002060` navy | Chrome — rail, top bar |
| **Action** | `#FF6A00` orange | **Action and attention only** — Approve, Revoke, Grant, alerts, pending, cost spikes. Never decorative. |
| Support | `#1BA4BE` cyan | Charts, sparklines, secondary accents |
| Neutrals | `#F0F4FA` `#E9EDF5` `#E0E4EA` | Surfaces. Cool and blue-tinted, never grey |

Dark mode lightens petrol to `#4FB8D6` for contrast and grounds on `#061A22` / `#0D2731`.
Orange shifts to `#FF8B3D`. Both themes follow the machine setting.

## Type

Roboto for everything readable. **Roboto Condensed** for dense data: employee codes, item
codes, table headers, refs, chips, eyebrows, and the logo wordmark. Both from Google Fonts.

## Copy

**No marketing copy anywhere in the product.** Removed and not to be reintroduced: greetings
("Good afternoon"), counts phrased as sentences ("Five services are open to you"), invitations
("Anything missing is a request away"), and reassurance ("All services healthy"). Labels and
data only. A heading names the page; it does not sell it.

## Entry page

**One page**: logo lockup, the two sign-in methods, then a **public list of every service**
underneath. Service names are visible before signing in — accepted deliberately, on the basis
that the deployment is VPN-only.

Clicking a service from that list goes straight to it:

- **In-house** (Item Code Studio, ATT, Service Desk, and everything built next) → the service bounces to MM OS to sign in, then returns with a token.
- **ERPNext and Twenty** → their own sign-in, pointed at the same Google accounts. They own their sessions; MM OS holds the tile and the grant only.

After signing in, the same surface becomes the services list with roles and status filled in.

## Service list

Rows, not icon tiles. Each row carries a **mark**:

- **Third-party** services use their own real logo (`brand/service-marks/`). Until the real SVG lands, a tile in the service's own brand colour with its initial stands in.
- **In-house** services use their initials in Roboto Condensed on petrol — `ICS`, `ATT`, `SD`, `AH`. Generated from the name, so a new service never lacks a mark.

Generic line icons are not used.

## Service Desk — four views

All four ship: **My requests**, **department queue with assignee**, **IT agent console**
(triage, assign, propose, resolve), and **approver decisions**.

**Department queue visibility:** everyone in the department sees every request raised by it,
including who it is assigned to and how long it has waited. A requester may mark a request
**private**, which limits it to the requester, the assignee and the approver — it still
appears in the queue as a hidden row so the count is honest, with no title or detail.

## Access page — four capabilities

All four ship: **per-person drill-down** (click a row for every service, role, who granted it
and when), **role meanings shown inline** (what `admin` actually permits on that service,
declared by the service and surfaced where the grant is made), **expiry dates and change
history**, and **pending access requests decided in place** on the same page, fed from Service
Desk.

## AI services page

Approved as designed. Restyled to the brand, structure unchanged.

## Console direction

**Chosen: direction B — top nav, calm.** Locked 24 Aug 2026. Directions A (rail and dense)
and C (command-first) are not built.

B is the `[data-dir="b"]` branch of `demo/console-directions.html`: a 60px navy top bar,
sticky, holding the logo lockup at 16px with the tagline suppressed, then the primary
destinations as flat text buttons — **Services · Service Desk · Access · AI services** — the
selected one in white with a 3px petrol underline, then a spacer, then Search, and the avatar
chip on the right. No left rail. Content sits in the calm, wider single column the direction
already lays out.

The command palette stays: it is B's Search button and `CTRL K`, not C's centrepiece.

The two unbuilt directions are **left in `demo/console-directions.html` for now** rather than
deleted, so the chosen one can still be diffed against them while the React shell is being
built. They come out once the shell is verified against B.
