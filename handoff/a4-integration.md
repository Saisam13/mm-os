# A4 · Integration kit

## Delivered

**`packages/mmos-client-py/`** — installable package (`pyproject.toml`, setuptools, no build-step
exotica; deps `fastapi`, `httpx`, `python-jose[cryptography]` only, matching `backend/requirements.txt`).

- `mmos_client/core.py` — `MMOS`, `CurrentUser`, `require_role`, `llm_guard`, `report_usage`.
  `MMOS.install(app)` adds `GET /_mmos/accept` (reads the token fragment client-side, POSTs to
  `/_mmos/session`, `history.replaceState`s it out), `POST /_mmos/session` (verifies, sets the
  HttpOnly cookie), `GET /_mmos/health`, an ASGI middleware that enforces the `public_paths`
  allowlist (fail-closed for anything not listed), and a startup-time route audit that logs a
  warning for any non-public route with no `mmos.user` / `require_role` dependency.
- `mmos_client/_verify.py` — token verification in the exact order from `docs/04-auth-flow.md`
  (kid → signature → iss → aud → exp/iat±60s → deny-list → roles), `alg` pinned to `RS256`
  explicitly before any key material is touched.
- `mmos_client/_jwks.py` — JWKS cache, refetch on unknown `kid`, rate-limited to once/minute.
- `mmos_client/_denylist.py` — in-memory deny-list + poller; `poll_once()` is the same call the
  background thread makes, exposed so it can be driven deterministically in tests.
- `mmos_client/_heartbeat.py` — usage accumulator + heartbeat loop; `beat_once()` likewise
  exposed directly.
- `tests/test_mmos_client.py` — 15 tests, all passing: valid token, wrong `aud`, expired,
  tampered signature, hand-built alg-confusion (HS256 signed with the RSA public key),
  revoked subject, revocation-within-one-poll, MM OS unreachable (degrades, doesn't fail
  closed), JWKS unknown-kid rate limiting, `llm_guard` default-open → closes after heartbeat,
  `report_usage` accumulate/ship/clear, `require_role` 403 shape, `public_paths` allowlist
  fail-closed, the accept/session cookie round-trip, `/_mmos/health`.
- `README.md` — 26-line copy-paste integration.

**`packages/embed/embed.js`** — one file, zero dependencies, 10.8 KB. Shadow-root render,
service learned from `location.hostname`, MM OS origin learned from its own `<script src>`.
Fetches `/api/me` with `credentials:"include"`, degrades to a plain "MM OS" link on failure.
Shows: back-to-MM-OS, a Cmd/Ctrl-K searchable switcher (only the services `/api/me` already
returned — the bar never filters further), open-ticket count, name + role-in-this-service.
One global (`window.MMOS`), one listener on the host document (Cmd/Ctrl-K, inert while an
input/textarea/contenteditable has focus).

- `packages/embed/test/smoke.js` — DOM-free (see `## Assumptions`): 5 checks via Node's `vm`
  module and a ~150-line hand-rolled DOM stub, run the real unmodified `embed.js`. All pass.
- `packages/embed/README.md` — the automated check plus a 5-step manual check for what a
  stub DOM can't cover (shadow isolation, dark mode, reduced motion, layout-shift bound).

**`examples/echo-service/`** — `main.py` (~90 lines) + `stub_mmos.py`. Public route, `mmos.user`
route, `require_role("admin")` route, `llm_guard()`/`report_usage()` route. Spins up a stub of
MM OS's public surface in a background thread so it runs standalone. `README.md` states the
one command. Manually verified end to end (see `## How to verify`), including the real
60-second revocation SLA against the actual background poller thread, not just the unit test.

## Deviations

- **`MMOS()` takes more constructor kwargs than the brief's literal signature** —
  `issuer` (defaults to `os_url`), `version`, `poll_after_seconds`, `heartbeat_seconds`,
  `jwks_min_refresh_seconds`, `clock_skew_seconds`, `llm_provider`/`llm_model`/`llm_key_present`,
  `cookie_name`, `http_client`. All optional with sane defaults; the four named in the brief
  (`slug`, `os_url`, `service_key`, `public_paths`) work exactly as documented on their own.
  `http_client` exists specifically so tests (and, if useful, a service's own tests) can inject
  an `httpx.MockTransport` instead of hitting the network.
- **Error envelopes are flattened.** FastAPI's default `HTTPException` handler wraps `detail`
  as `{"detail": {...}}`. The brief's shapes (`{"error":"role_required",...}`,
  `{"error":"llm_disabled"}`) are flat, so `install()` registers a small exception handler that
  unwraps any dict-valued `HTTPException.detail` to the top level. This affects every 401/403/503
  this library raises, not just `require_role`.
- **`require_role` / `llm_guard` / `report_usage` resolve against the most-recently-constructed
  `MMOS` instance**, not an instance passed explicitly — see `## Assumptions`.
- **The service's own cookie holds the raw MM OS-issued JWT**, not a separately-minted local
  session token. `/_mmos/session` verifies it once before setting the cookie; every later
  request re-verifies it via the same `_verify()` path (cheap: the JWKS lookup is cached). This
  keeps the client stateless — no session store to add — at the cost of re-running signature
  verification on every request, which is the same cost any bearer-token API pays.
- **`docs/05-service-integration.md`'s own example doesn't match a literal-prefix reading of
  `public_paths`**: it lists `public_paths=["/api/public"]` then defines a route at
  `/api/public/lookup`. I implemented `public_paths` entries as prefixes (`path == p` or
  `path.startswith(p.rstrip("/") + "/")`), which is what makes that example consistent — flagged
  under `## Contract objections` since it's a doc ambiguity, not something I could "fix" locally.
- **embed.js is 10.8 KB, not "under ~10KB.".** After a compaction pass (short class names,
  short CSS custom properties, no blank lines) it's ~7% over the approximate target. The
  remainder is the switcher's markup/logic and the light+dark token set; cutting further would
  mean dropping a required feature (search, keyboard nav, or theme support) rather than
  trimming waste. Flagging rather than silently shipping over budget.
- **embed.js does not load Roboto / Roboto Condensed.** `demo/console-directions.html` uses
  Google Fonts; embed.js uses the system font stack instead, to avoid an external network
  request and stay dependency-free on a script that ships to every service including
  third-party ones (ERPNext, Twenty). Colors (petrol/navy/orange/cyan) and the dark-mode /
  chip / pill visual language are matched from that file.

## Contract objections

- **`demo/index.html` does not exist.** The brief names it twice as "the bar's visual
  language." Only `demo/console-directions.html` and `demo/_superseded-first-prototype.html`
  are present. I built `embed.js`'s look from `console-directions.html` (CSS custom
  properties, chrome/petrol/orange palette, chip and command-palette styling, dark-mode
  block) since it's the more current-looking of the two and self-describes as the active
  direction-picker doc. If `demo/index.html` is meant to exist and simply hasn't landed yet,
  the bar may need a follow-up pass once it does.
- **`docs/05-service-integration.md`'s Python example is inconsistent with a strict reading
  of `public_paths` as exact paths** (see `## Deviations` above) — worth tightening in the
  doc to state explicitly that entries are prefixes, since that's the only reading under
  which the example's own route (`/api/public/lookup` against `public_paths=["/api/public"]`)
  is actually public.
- **Neither `docs/03-api-contract.md` nor `docs/04-auth-flow.md` specifies the wire shape of
  `POST /_mmos/session`** (the call `/_mmos/accept`'s script makes) or names it at all —
  `docs/04` only says `/_mmos/accept` "reads the fragment, sets the service local cookie."
  I designed it as `POST {"token": "<jwt>"}` → `204/200` + `Set-Cookie`, which is the natural
  reading, but another agent building a second client library from scratch could reasonably
  invent a different shape (e.g. a different field name, or folding verification into the
  `GET /_mmos/accept` request itself via a query string — which would be worse, since query
  strings get logged, unlike the fragment). Worth pinning down explicitly in `docs/05` since
  it's the one MM OS-facing wire format that isn't service-to-service (it's browser-to-service).
- **The heartbeat's `llm` object shape is specified in `docs/03` but nothing says how a
  service is supposed to *know* its own provider/model/key_present** — that's inherently
  service-specific configuration with no MM OS-side input, so I added it as optional `MMOS()`
  kwargs (see `## Deviations`). Worth confirming that's the intended shape, since the
  alternative (a separate `mmos.set_llm_info(...)` call) is just as reasonable.

## Assumptions

- **One `MMOS()` instance per process.** `require_role(...)`, `llm_guard()` and
  `report_usage(...)` are specified as free functions with no way to pass an instance
  (`llm_guard()` takes zero arguments), so they resolve against a module-level "most recently
  constructed" `MMOS`. This matches every example in `docs/05` and the echo-service — a
  service mounts exactly one `MMOS`. A service that legitimately needs two would need a
  different API shape entirely; flag if that's a real scenario.
- **`llm_enabled` defaults to `True` until the first heartbeat lands**, not `False`. The
  alternative (fail closed until proven otherwise) would 503 every LLM route across the
  company for however long MM OS takes to come up after a restart, which reads as exactly
  the outcome the brief's "keep serving, don't fail closed" philosophy is written against for
  the deny-list — I extended the same logic to the LLM gate. If MM OS actually wants LLM
  access to default OFF until explicitly enabled, this needs to flip.
- **`require_role` does not give `platform_admin` an automatic bypass** of a service's own
  role check. `platform_admin` is an MM OS-platform concept; a service's roles are its own
  local vocabulary (`docs/05`'s example uses `"admin"`, `"viewer"` — service-defined, not
  MM OS-defined), so I did not conflate the two. A platform admin who also needs `"admin"` in
  a given service should be granted that role like anyone else.
- **`public_paths` prefix-matches** rather than exact-matches (see `## Contract objections`).
- **The cookie set by `/_mmos/session` is `{slug}_mmos_at`**, `HttpOnly`, `Secure`,
  `SameSite=Lax`, `path=/`. Nothing in `docs/03`/`docs/04`/`docs/05` names this cookie, so any
  other agent building a second client for the same runtime (unlikely, but possible for a
  non-Python service reusing this cookie name convention) should match it or pick their own —
  they're independent per-service cookies by design, not shared.
- **`embed.js`'s app switcher shows every service `/api/me` returns**, with no additional
  client-side filtering — per `docs/03`, `/api/me`'s `services` array is already scoped to
  what the person may open, so re-filtering client-side would be redundant, not safer.

## Not done

- Nothing from the brief's acceptance list was skipped. The one thing not exercised live
  end-to-end (only via the unit test) is the 5-minute heartbeat's LLM-disable pickup — proving
  it live means either waiting 5 real minutes or reducing `heartbeat_seconds` for the demo,
  and I judged the deterministic `heartbeat.beat_once()` test plus the documented curl
  recipe in `examples/echo-service/README.md` sufficient. The mechanism (cache flag, no
  request-path network call) is identical to the revocation poller, which *was* proven live
  end to end against the real 60-second interval.
- `mmos-client-py` is not `pip install`-ed into the shared `backend/.venv` (deliberately —
  see `## Assumptions` in spirit, and the guardrail against touching the shared venv). Tests
  and `examples/echo-service` reach it via `sys.path`/`conftest.py`. A real consumer installs
  it normally; nothing here blocks that.
- No coverage of Alembic/Postgres-specific behavior — not applicable to this kit, it never
  touches the database.

## How to verify

```bash
# mmos-client-py unit tests (15, all passing)
backend/.venv/Scripts/python.exe -m pytest packages/mmos-client-py/tests -q

# embed.js — DOM-free smoke test (5 checks, all passing)
node packages/embed/test/smoke.js

# echo-service — one command, runs standalone against its own embedded MM OS stub
backend/.venv/Scripts/python.exe examples/echo-service/main.py
# then, in another shell:
curl http://127.0.0.1:8090/_mmos/health
TOKEN=$(curl -s "http://127.0.0.1:8090/_demo/mint?roles=viewer" | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl http://127.0.0.1:8090/api/whoami -H "Authorization: Bearer $TOKEN"
curl -X POST http://127.0.0.1:8090/api/admin/note -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}'
# -> 403 {"error":"role_required","need":"admin","have":["viewer"]}
```

Full curl walkthroughs for the admin route, the LLM route, the 60-second revocation SLA
against the real background poller, and the LLM kill switch are in
`examples/echo-service/README.md` — the revocation one was run live during this build
(revoke → wait 60s → 401 `revoked`), not just unit-tested.
