# 01 · Architecture

## The constraint that shapes everything

ERPNext runs on **Frappe Cloud SaaS** (`minimines-uat.m.frappe.cloud`). We do not control
that box, cannot put it behind our own gateway, and cannot install middleware in it.

Therefore MM OS cannot be the thing all traffic flows through. It is an **identity,
directory and workflow layer**. Services keep their own hostnames and keep serving their own
traffic; MM OS tells them who the visitor is and what they may do.

That is also why the system survives change: swap ERPNext or Twenty tomorrow and MM OS does
not move.

## Layers

| Layer | Owner | Notes |
|---|---|---|
| Authentication — *is this really Prashanth?* | Google Workspace (OIDC) | Locked to `hd=m-mines.com`; MFA enforced in the Workspace admin console. PIN fallback for staff with no mailbox. |
| Authorization — *what may Prashanth open?* | **MM OS** | `employees`, `services`, `service_roles`, `grants`. Google has no idea what Item Code Studio is, so this can never live there. |
| Token issuing — *why should a service trust MM OS?* | **MM OS** | RS256 JWT, 15-minute life, `aud` = exactly one service. Verified offline against JWKS. |
| Revocation | MM OS + client library | Services poll `/api/revocations` every 60s. Accepted SLA: access dies within 60s of removal. |
| Service runtime | each service | Own Coolify container, own Postgres database. MM OS being down must not stop work already in progress. |

No Keycloak, no Authentik. They earn a container only when two or more **third-party** apps
need SAML and refuse anything custom. Because MM OS tokens use standard OIDC-shaped claims,
adding a broker later is configuration, not a rewrite.

## Trust model in one paragraph

MM OS holds a private key. Every service holds nothing but the MM OS public key (fetched
from `/.well-known/jwks.json`, cached one hour) plus a service key used only for
server-to-server calls. A user arriving at a service presents a JWT whose `aud` is that
service and whose `roles` claim lists their roles *there*. The service verifies the
signature locally — no network round trip on the hot path — and separately keeps a
60-second-fresh deny-list, so a departing employee loses access before their token expires.

## Navigation: hybrid handoff plus shared chrome

Services keep their own subdomains and open as SSO handoffs, so nothing has to be rewritten
and nothing breaks inside an iframe. What makes it feel like one product is a **single
script served by MM OS** and included by every service:

```html
<script src="https://os.m-mines.com/embed.js" defer></script>
```

It renders, inside a **shadow root** (so host CSS can never break it and it can never break
the host): back-to-MM-OS · app switcher (Ctrl/Cmd-K, searchable, filtered to what you may
open) · open ticket count · your name and your roles in *this* service. Because the script
is served by MM OS, adding a new service updates the switcher inside every app at once, with
no redeploys anywhere.

### The entry page, and who owns each session

Decided 23 Aug 2026. The entry page is **one page**: logo, the two sign-in methods, and a
**public list of every service** underneath, visible before signing in. That list is a
directory people can enter through directly, and what happens on a click depends on who owns
the session:

| Clicked | What happens | Who owns the session |
|---|---|---|
| Item Code Studio, ATT, Service Desk, anything in-house | the service redirects to MM OS, you sign in once, it returns you with a token | MM OS |
| ERPNext, Twenty CRM | their own sign-in, pointed at the same Google Workspace accounts | the service |

The second row is not a compromise, it is the truth: ERPNext is SaaS and owns its own session
whatever we do. Because both routes authenticate the same Google identity, it is the same
person either way, and MM OS still holds the tile, the grant and the audit record of who was
given access.

**Consequence to accept:** the service list is visible to anyone who can reach the login page.
On a VPN-only deployment that is a small exposure, and it was accepted deliberately so that
people who already have an account somewhere can go straight there. It also means the public
list endpoint must return **names and launch URLs only** — never roles, health, or anything
about who works here.

| Service class | How the bar gets in |
|---|---|
| Ours (ATT, Item Code Studio, Service Desk, future) | one `<script>` line in `index.html` |
| ERPNext (SaaS) | **Navbar Settings → custom navbar items** — an in-app setting, no custom app needed on Frappe Cloud |
| Twenty CRM (self-hosted) | same script tag in its build |
| Anything locked down | opens in a new tab; MM OS stays alive in tab 1, installed as a **PWA** so it is a permanent window |

## LLM: control plane, not data plane

API keys stay in each service settings page, exactly as ATT_Platform does today. MM OS never
stores a key, so there is no central secret to leak. What MM OS gets is visibility and a
switch:

- each service reports on heartbeat: `provider`, `model`, `key_present`, `enabled`, and rolling token counters
- the admin page lists every service using an LLM, what it is consuming, and when it was last seen
- toggling a service **off** flips a flag the service reads on its next config poll; the key stays put and AI features simply stop

**Consequence to respect:** MM OS can only display what services report. The usage-reporting
hook ships in `mmos-client-py` from day one — a service that skips it shows as `unreported`,
which is deliberately visible rather than silently blank.

## Deployment shape

Coolify on the Hostinger VPS. One Postgres instance with one database and one role per
service — isolated data, a single engine to back up and tune. MM OS itself is a **single
container**: FastAPI serves the API and the built React bundle on one port, which is the
ATT_Platform pattern that already works here.

## Network posture

MM OS is **not internet-facing**. It is reachable only from the office network or over
WireGuard. Enforced in two independent places: the VPS firewall, and a CIDR allowlist
middleware in the app (`NETWORK_MODE=private`). Flipping to internet-facing later is one
environment variable. The one real cost of this choice is running Google OIDC against a
privately-resolved host — see [06-network-security.md](06-network-security.md).

## Known risks, carried deliberately

1. **Two employee masters will drift.** MM OS is authoritative for access; ERPNext keeps its
   own Employee records. A reconciliation report is on the v2 list, not v1.
2. **Revocation is only as fast as the poll.** 60s is the agreed SLA. Instant revocation
   would need webhook fan-out to every service.
3. **Dual-mode services are one routing slip from exposure.** Mitigated structurally, not by
   discipline: every write endpoint lives under a single middleware-guarded prefix and the
   public surface reads through a read-only database role. See
   [05-service-integration.md](05-service-integration.md).
4. **LLM visibility depends on service cooperation.** Unreported is shown as unreported.

## What MM OS deliberately is not

- not a reverse proxy — services are reached directly
- not a data warehouse — identity, grants, registry, audit; nothing about batteries
- not a ticketing system — Service Desk is its own service with its own database
- not an HR system — it holds only the employee fields that access decisions need
