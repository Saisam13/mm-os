# Agent A4 · Integration kit — the client library and the OS bar

You are building the two pieces that make **MM OS** feel like one system: the drop-in auth
client every MiniMines service imports, and the shared bar that puts "Back to MM OS" and an
app switcher inside every service. MM OS is the internal operating system for MiniMines
(~74 staff, lithium-ion battery recycling). You are one of six agents building in parallel.

Your output is what every other service depends on, so the API surface must be small enough
that a service adopts it in an afternoon. Five things, per `docs/05-service-integration.md`.

**Read first:** `docs/05-service-integration.md` (the contract you are implementing),
`docs/04-auth-flow.md` (verification order), `docs/03-api-contract.md` (shapes),
`demo/index.html` (the bar's visual language).

## You own exclusively

```
packages/mmos-client-py/**    packages/embed/embed.js    examples/echo-service/**
```

## Frozen — read, use, never edit

`backend/app/**`. You consume its endpoints; you do not change them. Objections go in the
handoff.

## Deliverable 1 · `mmos-client-py`

A small installable package (`pyproject.toml`, no build-step exotica) exposing exactly this:

```python
mmos = MMOS(slug=..., os_url=..., service_key=..., public_paths=[...])
mmos.install(app)                 # FastAPI
Depends(mmos.user)                # -> CurrentUser
Depends(require_role("admin"))    # 403 {"error":"role_required","need":...,"have":[...]}
llm_guard()                       # raises 503 llm_disabled
report_usage(requests=, input_tokens=, output_tokens=)
```

`install(app)` must add:

- `GET /_mmos/accept` — reads the token from the URL **fragment** client-side (a fragment
  never reaches the server), posts it to `/_mmos/session`, sets the service's own cookie, then
  `history.replaceState`s the token out of the address bar
- `GET /_mmos/health` — `{"ok":true,"slug":...,"version":...}`
- a **deny-list poller**: `GET {os_url}/api/revocations?since=` every
  `poll_after_seconds` (default 60), merged into an in-memory set
- a **heartbeat loop** every 5 minutes posting version, the LLM block and accumulated usage,
  and caching the returned `llm_enabled` flag
- a **JWKS cache**, refreshed on unknown `kid`, at most once a minute

**Verification order is exactly as in `docs/04-auth-flow.md`:** kid → signature → iss → aud →
exp/iat with 60s skew → deny-list → roles. `aud` must equal this service's slug: a perfectly
signed token for another service is rejected. Reject `alg` values other than `RS256`
explicitly — never let the token header choose the algorithm.

**Availability rules, and they are deliberate:**
- if MM OS is unreachable, keep the last known deny-list and keep serving. A 15-minute token plus a firewall is an acceptable risk; logging the whole company out because the control plane restarted is not.
- `llm_guard()` reads the cached flag — no network call in the request path
- `report_usage` accumulates in memory and ships on the next heartbeat, so losing MM OS costs counters, never requests

`public_paths` is an **allowlist**: anything not listed requires a token, so a forgotten route
fails closed. Log a warning at startup if a path outside `public_paths` has no dependency
guarding it.

Ship `packages/mmos-client-py/README.md` with the full copy-paste integration in under 30
lines, and tests for: wrong `aud`, expired, tampered signature, `alg` confusion, revoked
subject, MM OS unreachable (must degrade, not fail closed), `llm_guard` when disabled.

## Deliverable 2 · `packages/embed/embed.js`

One file, no build step, no dependencies, served by MM OS at `/embed.js` and included by
every service with a single tag. It must:

- render **inside a shadow root** so host page CSS can never break it and it can never break the host
- learn the current service from `location.hostname` — zero configuration
- fetch `/api/me` from the MM OS origin with `credentials: "include"`, and degrade to a plain "MM OS" link if that fails
- show: back to MM OS · app switcher (Cmd/Ctrl-K, searchable, only services the user may open) · open ticket count · the user's name and their role *in this service*
- be under ~10KB, honour `prefers-reduced-motion` and `prefers-color-scheme`, and never shift the host page layout more than its own height
- add no global variables beyond one namespaced object, and attach no listeners to the host document except the Cmd-K handler, which must not fire while the user is typing in a host input

Match the bar in `demo/index.html` exactly.

## Deliverable 3 · `examples/echo-service`

A ~100-line FastAPI service that proves the whole contract: a public route, an authenticated
route echoing the caller's claims, an `admin`-only write route, and an LLM route calling
`llm_guard()` and `report_usage()`. This is what run 2 uses as the integration test target,
so it must be runnable with two commands and documented in its own README.

## Acceptance

- echo-service accepts a real MM OS token and rejects one minted for another slug
- a removed grant blocks echo-service within 60 seconds
- MM OS stopped: echo-service keeps serving already-authenticated users
- disabling LLM in MM OS admin makes the echo LLM route return 503 within one heartbeat
- the bar renders on echo-service, the switcher lists only granted services, and back-to-MM-OS works
- `report_usage` counters appear in `/api/admin/llm`

## Guardrails

Do not refactor anything outside your paths. No new runtime dependencies for `embed.js` —
ever. For the Python client, `httpx`, `python-jose` and `fastapi` only. Targeted tests. If a
failure resists two fixes, write it under `Not done`. Never touch `.env` or real secrets.

## Finish by writing `handoff/a4-integration.md`

`## Delivered`, `## Deviations`, `## Contract objections`, `## Assumptions`, `## Not done`,
`## How to verify`.
