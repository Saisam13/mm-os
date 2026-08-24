# B2 · Retrofit — ATT Platform

**Scope note, agreed with the orchestrator before starting:** Item Code Studio does not exist
on this machine. Searched Desktop, Documents, OneDrive and `D:` again; the only item-code
material is one-off spreadsheet scripts under `Erp Imp/Files created for tasks/`, not an
application with a PIN gate. Nothing was invented or scaffolded. `backend/app/seed.py`'s
`itemcode` service-registry row (placeholder `base_url`) was **not touched** — read-only per
the guardrails, and left exactly as-is so the tile exists when the service eventually does.
ERPNext/Twenty CRM configuration (also named in `agents/B2-retrofit.md`) is likewise not
covered here — the live task redirected this run to ATT Platform only. The rest of this
document is ATT Platform, in full.

**Repo:** `C:/Users/Anura/OneDrive/Desktop/ATT_Platform` (its own git repo, not part of this
monorepo). **Branch:** `mmos-retrofit`, created off `master` (never `main`/`master` directly,
never force-pushed, not pushed to any remote). **Two commits on the branch, `master` still
at the repo's original `b794201`:**
1. `2be2337` — "Wire ATT into MM OS auth; delete the shared-PIN gate" (the work described
   throughout this document).
2. `7a60e4a` — "Fail closed on missing MM OS auth config, not open" — a coordinator-requested
   correction, made after review and before merge, to the fallback described in
   `## Deviations` #5. Nothing in commit 1 was amended; this is a second commit on top.

## Delivered

**Auth wiring**

- `backend/vendor/mmos_client/` — a **vendored, verbatim copy** of this repo's
  `packages/mmos-client-py/mmos_client/` (all six files: `__init__.py`, `core.py`,
  `_denylist.py`, `_heartbeat.py`, `_jwks.py`, `_verify.py`; `__pycache__` excluded). ATT
  Platform is a separate git repository with no path to this monorepo's package at
  deployment time, and `mmos-client-py` isn't published anywhere yet (README already says as
  much), so a straight copy is the only option that doesn't leave ATT's build depending on
  this repo's filesystem layout. Provenance and re-sync instructions are in the vendored
  `__init__.py`'s docstring. `requirements.txt` gained `httpx>=0.28,<1` and
  `python-jose[cryptography]>=3.3,<4` (the two real deps `mmos_client` needs beyond `fastapi`,
  which ATT already pins) — installed into **ATT's own venv**, not this repo's shared one.
- `backend/mmos_integration.py` (new) — constructs `MMOS(slug="att", os_url=…,
  service_key=…, public_paths=[], …)` from env vars (`MMOS_OS_URL` default
  `https://os.m-mines.com`, `MMOS_SERVICE_SLUG` default `"att"`, `MMOS_SERVICE_KEY`,
  `MMOS_ISSUER` default = `MMOS_OS_URL`). Exposes `current_user` (any role) and
  `require_admin` (the `admin` role, same `403 {"error":"role_required","need":"admin",
  "have":[...]}` shape as `mmos_client.require_role`, no `platform_admin` bypass — matching
  the answer B1 gave for Service Desk) as FastAPI dependencies, plus `llm_guard()` and a
  re-exported `report_usage()`. **Local-dev fallback:** if `MMOS_SERVICE_KEY` is unset, the
  MM OS middleware is never installed at all and every dependency resolves to a synthetic
  local `admin` `CurrentUser` — loudly logged, never silent. See `## Deviations` for why this
  exists.
- `backend/main.py` — **the PIN gate is deleted, not commented out**: the `pin_gate`
  middleware, the `PinIn` model, and `POST /api/auth/verify` are gone entirely. In their
  place, `install_mmos(app)` is called immediately after the `FastAPI()`/CORS lines (before
  the SPA catch-all is registered later in the file, so `/_mmos/accept`/`/_mmos/session`/
  `/_mmos/health` are matched ahead of it). **Every one of ATT's 25 routes now carries an
  explicit `Depends`** — `current_user` on every read, `require_admin` on every mutation
  except two deliberate exceptions (see `## Deviations`). `llm_guard()` is called in
  `POST /api/runs` (only when `use_llm=true`) and `POST /api/settings/test-llm`, both before
  any provider call is made.
- `backend/llm.py` — `_call_anthropic`/`_call_gemini`/`_call_ollama` now return
  `(text, usage)`, with `usage` read straight off each provider's own response
  (`usage.input_tokens`/`output_tokens` for Anthropic, `usageMetadata.promptTokenCount`/
  `candidatesTokenCount` for Gemini, `prompt_eval_count`/`eval_count` for Ollama — real
  counts, not estimates). `LlmMatcher.__call__` (the actual matcher, run inside
  `backend/runner.py`'s background thread) and `main.py`'s `test_llm` both call
  `report_usage()` immediately after each successful provider call.
- `backend/settings.py` — `pin_enabled`/`pin_code`/`SECRET_KEYS` removed from `DEFAULTS`.
  `get_all()` now skips any stored settings row whose key isn't in the current `DEFAULTS`, so
  a retired key can't resurrect itself from an old database row — found and needed, because
  the dev database (`data/att.db`) already had a stale `pin_enabled: false` row from before
  this change; deleted directly (see `## Deviations`).
- `frontend/src/api.ts` — the `pin` object, `X-ATT-Pin` header injection, and `verifyPin`
  call are gone. Auth is now the browser-attached MM OS session cookie
  (`att_mmos_at`, `HttpOnly`); a `401` dispatches `mmos-auth-required` instead of
  `att-pin-required`.
- `frontend/src/App.tsx` — `PinScreen` → `AuthRequiredScreen`: no local login form any more
  (there's nothing to log into locally), just a message and a link back to
  `https://os.m-mines.com/`.
- `frontend/src/pages/SettingsPage.tsx` — `SecurityPanel` (the PIN toggle/set UI) removed
  entirely, along with its call site.
- `frontend/index.html` — `<script src="https://os.m-mines.com/embed.js" defer></script>`
  added in `<head>`. Confirmed present in the built `dist/index.html` after `npm run build`.
- `.claude/launch.json` — added a `"backend"` entry (`uvicorn backend.main:app --port 8000`)
  alongside the pre-existing `"frontend"` one, documenting the one-line way to boot the API.

**What the PIN gate protected, and what protects it now:** the PIN gate (`x-att-pin` header
checked against a single shared `pin_code` setting, `settings.pin_enabled`) sat in front of
every `/api/*` route (`/api/auth/verify` itself excluded, by design) as a single shared secret
— one PIN for the whole team, entered once per browser and cached in `localStorage`. It
protected the entire API uniformly, with no distinction between reading a dashboard and
starting a run. It is now replaced by **MM OS's per-person, per-role token**: every route
requires a valid MM OS-issued, RS256-signed JWT (verified by `mmos_client`'s JWKS/deny-list
pipeline) carrying `aud=att`, and mutations additionally require the `admin` role on that
token. This is strictly stronger — individual identity instead of a shared secret, per-route
role granularity instead of an all-or-nothing gate, and revocation within 60 seconds of an
admin removing someone's grant instead of a PIN that stays valid until manually rotated.

**Which routes remain anonymous, and why:** **none.** `public_paths=[]` — ATT has no
anonymous surface at all (unlike Item Code Studio's planned public lookup, this is a single-
mode internal tool). The only paths reachable without a token are the three MM OS hardcodes
`/_mmos/accept`, `/_mmos/session`, `/_mmos/health` (`mmos_client.core._ALWAYS_PUBLIC` — not
app-defined, and required by the handoff protocol itself: the browser can't present a cookie
it doesn't have yet on its first hit to `/_mmos/accept`). Every other path — the SPA shell
included — is behind the ASGI middleware's fail-closed allowlist check, whether or not its
route handler also declares an explicit dependency.

**Roles:** `viewer` (default, read-only — dashboards, rankings, raw trade data, geo/
regulatory logs, exports, and submitting trader feedback) and `admin` (everything a viewer
can do, plus starting/renaming/deleting runs, uploading trade files and base portfolios,
editing scoring weights and settings, and managing the LLM provider/key). Exact endpoint
split:

| Guard | Routes |
|---|---|
| `current_user` (any role) | every `GET`, plus `POST /api/feedback` and `POST /api/runs/{id}/preview-weights` (see `## Deviations`) |
| `require_admin` | `POST /api/runs`, `POST /api/battery-runs`, `PATCH /api/runs/{id}`, `DELETE /api/runs/{id}`, `PUT /api/settings`, `POST /api/settings/test-llm` |

**Whether ATT uses an LLM: yes**, optionally. Three providers (`anthropic`, `gemini`,
`ollama`), off by default, configured in Settings and used only to re-match trade-description
rows the rule-based matcher scored below 60%. `llm_guard()` sits at the two points that can
trigger a provider call (`POST /api/runs` when `use_llm=true`, `POST /api/settings/test-llm`)
and `report_usage()` reports real token counts wherever a provider actually returns — see
`## Not done` for what wasn't exercised live (no API key/Ollama instance in this sandbox).

## Deviations

1. **Vendored `mmos-client-py` instead of `pip install`-ing it** — see `## Delivered`. This
   is a real fork risk (a security-relevant library now has two copies to keep in sync); the
   vendored `__init__.py` names exactly which six files to re-copy if the source changes.
2. **Roles are `viewer`/`admin`, not `viewer`/`runner`.** `agents/B2-retrofit.md` (the
   original brief) said `runner`; the live task redirected this explicitly ("Roles: whatever
   ATT actually needs — most likely `viewer` and `admin`"), which is what the acceptance
   checklist itself is worded against ("a route requiring `admin` returns 403 for a
   `viewer`"). Implemented as instructed.
3. **Two `POST` routes deliberately stayed on `current_user`, not `require_admin`:**
   - `POST /api/feedback` — trader feedback is meant for every team member, not just admins;
     gating it to `admin` would defeat the Feedback page's whole purpose. It was reachable by
     anyone behind the PIN before this change, and "any signed-in MM OS user" is the closest
     equivalent, not "admin only."
   - `POST /api/runs/{id}/preview-weights` — a live what-if recompute from already-stored
     scores; the docstring already says "nothing is saved." It's a `POST` verb for payload-size
     reasons (the weights object), not because it mutates anything, and it's presented in the
     UI alongside other read-only views.
4. **`llm_guard()` lives at the synchronous request entry points, not inside the actual
   matcher call.** The real batched LLM matching happens inside `backend/runner.py`'s
   `threading.Thread` background worker, not the request/response cycle — `llm_guard()`
   raises an `HTTPException`, which is meaningless outside a request context. So it's called
   in `POST /api/runs` (only when `use_llm=true`) and `POST /api/settings/test-llm`, both
   *before* any background work is queued: if MM OS's kill switch is off, run creation itself
   503s rather than silently starting a run that will skip the LLM stage anyway (or, in a
   race, running it under a canceled entitlement). `report_usage()` has no such constraint —
   it's a lock-protected in-memory counter (`mmos_client._heartbeat.UsageAccumulator`), so it
   is called directly from the background thread, from `backend/llm.py`, right where each
   provider's response actually lands.
5. **Local-dev fallback, corrected mid-review to fail closed — this is the one deviation
   that changed shape after the branch was first built.** The first version of
   `backend/mmos_integration.py` set `MMOS_ENABLED = bool(MMOS_SERVICE_KEY)`: no key meant
   dev mode, silently. The coordinator caught this before merge and it was wrong — that's
   **fail-open**, not fail-closed. A secret renamed in Coolify, a variable forgotten when a
   new environment is created, or someone running the container by hand to debug would all
   silently produce an unauthenticated admin console, indistinguishable from a healthy
   deployment because every request still returns `200`. Deleting the PIN gate and replacing
   it with "no auth at all if misconfigured" would have been a net security loss, not a gain.

   **The corrected, final contract** (commit `7a60e4a`, second commit on this branch — the
   first commit, `2be2337`, still has the fail-open version in its history but is not what
   ships): exactly one of two env vars may be set, and `backend/mmos_integration.py` calls
   `sys.exit()` — refusing to start the process, not serving a 401 wall — in every other case:

   | `MMOS_SERVICE_KEY` | `ATT_DEV_NO_AUTH` | Result |
   |---|---|---|
   | unset | unset | **refuses to start** — the message names both variables and what to set |
   | unset | `1` | boots in dev mode: every route open to a synthetic, obviously-fake user (`name="⚠ LOCAL DEV — NO MM OS AUTH ⚠"`, `employee_code="DEV-NO-AUTH"`); logged loudly on every boot |
   | set (any real key) | unset | boots in real mode: MM OS auth installed exactly as described above |
   | set | `1` | **refuses to start** — both together can only be a mistake (e.g. a leftover dev flag carried into a real deployment) |

   `ATT_DEV_NO_AUTH=1` is a positive, deliberate statement of intent — nobody sets it by
   accident the way an *absent* variable can go unnoticed. `GET /api/settings` now returns
   `"auth": {"mmos_enabled": false}` whenever the dev bypass is active, and
   `frontend/src/App.tsx` renders a fixed red banner ("LOCAL DEV MODE — MM OS AUTH IS
   DISABLED") across the top of every page in that mode — a developer can never be in doubt
   about which mode they're looking at. `mmos.install(app)`'s own ASGI middleware still fails
   closed on everything once installed (`public_paths=[]`, so even the SPA shell needs the
   token) — that part of the design was already correct and is unchanged; the fallback logic
   deciding *whether* to install it at all is what moved from fail-open to fail-closed.

   Verified live (all four boot cases, real subprocess boot, real exit codes) via
   `scripts/verify_boot_modes.py` (new, committed) plus the existing 19-check acceptance
   suite re-run with no regressions — see `## How to verify`.
6. **`refresh_llm_info()` reaches into `mmos.heartbeat`'s private `_llm_provider`/
   `_llm_model`/`_llm_key_present` fields directly**, called from `PUT /api/settings` when an
   admin changes the `llm` block. `MMOS()` only accepts these as constructor kwargs with no
   public setter (this repo's own `handoff/a4-integration.md` names the same gap under its
   "Contract objections"). Cosmetic only — it changes what `/api/admin/llm` displays as ATT's
   declared provider/model, never authentication or the kill switch itself, which the
   heartbeat already re-reads live regardless.
7. **Cleaned up two stale rows in the local dev database** (`data/att.db`:
   `pin_enabled=false`, no `pin_code` row) and hardened `settings.get_all()` to ignore any
   future row whose key isn't in `DEFAULTS` — belt-and-suspenders so a retired setting can't
   silently come back from an old row. Also deleted three run rows (`id` 7–9) and their
   `data/uploads/` directories that this handoff's own acceptance testing created against the
   real `create_run` endpoint — cleanup of test exhaust, not a functional change.

## Contract objections

None new against this repo's frozen docs. ATT is a single-mode service (`public_paths=[]`),
so it never touched the dual-mode structural rules (`docs/05`'s three non-negotiable rules)
that Item Code Studio would have exercised — nothing here confirms or refutes those rules'
soundness. The one thing worth naming: `docs/05-service-integration.md`'s only worked Python
example is the dual-mode one (`public_paths=["/", "/lookup", "/api/public"]`); a first-time
integrator building a single-mode, fully-internal service like ATT has to infer that
`public_paths=[]` is valid and means "no anonymous surface at all" — it isn't shown anywhere.
Minor documentation gap, not a defect; `mmos_client.core.MMOS._is_public` handles the empty
list correctly (confirmed: every ATT route 401s with no token, `## How to verify`).

## Assumptions

1. **No reachable MM OS instance exists in this sandbox**, and this task's environment note
   said the orchestrator is separately running the full-mode acceptance suite against this
   repo's own backend — running a second local MM OS instance to actually register `att` felt
   like exactly the kind of interference "do not run Docker, you don't need it" and "reference
   only" were guarding against, so it wasn't attempted. Instead, the entire client wiring was
   proven end to end against a **throwaway stub MM OS** — the same `stub_mmos.py` this repo's
   own `examples/echo-service` already uses — with `examples/echo-service` itself standing in
   as the second, cross-rejecting real service (per this task's own instruction, replacing
   Item Code Studio for that specific test). See `## How to verify` for the full script and
   result. **A human still needs to do the real registration** once a live MM OS is available,
   with exactly these three calls (`docs/05`'s own recipe, adapted):
   ```bash
   curl -X POST https://os.m-mines.com/api/admin/services \
     -H 'Content-Type: application/json' -b mmos_session=… \
     -d '{"slug":"att","name":"ATT Platform","base_url":"<ATT'\''s real deployed URL>",
          "category":"commercial","icon":"flask","launch_mode":"handoff"}'

   curl -X POST https://os.m-mines.com/api/admin/services/att/roles \
     -d '{"key":"viewer","name":"Viewer","is_default":true,
          "description":"Browse dashboards, rankings, raw trade data, and exports; submit trader feedback. Cannot start runs, upload portfolios, or change scoring settings."}'

   curl -X POST https://os.m-mines.com/api/admin/services/att/roles \
     -d '{"key":"admin","name":"Admin",
          "description":"Everything a viewer can do, plus start/rename/delete runs, upload trade files and base portfolios, edit scoring weights and settings, and manage the LLM matcher provider/key."}'
   ```
   The service key that step 1 returns goes into ATT's deployment environment as
   `MMOS_SERVICE_KEY` (plus `MMOS_OS_URL`/`MMOS_SERVICE_SLUG` only if they differ from the
   defaults already baked into `backend/mmos_integration.py`).
2. **Rename/delete-run classified as `admin`-only.** The brief's exact wording ("starts a
   run, uploads a portfolio, edits settings or touches the LLM") doesn't literally name
   rename/delete. Treated as the same bucket as run creation (run *management*, not read-only
   viewing) — a defensible but not the only reasonable call; flagging rather than assuming.
3. **`preview-weights` and `feedback` classified as viewer-level** despite being `POST`
   verbs — justified in `## Deviations` #3, but it's a judgment call on "what counts as a
   mutation," not something the brief spelled out route-by-route.
4. **ATT's own name-picker (the "who's using the platform" modal, `localStorage.att_user`,
   stamped on feedback/settings-log rows) was left completely untouched.** MM OS's
   `CurrentUser.name`/`employee_code` is now available on every request and is a strictly
   better source of truth than a free-text browser-local name a person could type inaccurately
   — but swapping it in changes product behavior (every feedback/settings-log row's
   attribution) beyond "thread auth through, don't modernize." Left as a deliberate
   non-change; worth a real follow-up once this is live.
5. **The 15-minute token lifetime (`docs/04-auth-flow.md`'s `exp=+15m`) is inherited
   as-is** — ATT's cookie holds the raw MM OS JWT (A4's own design choice, not something
   changeable from a consuming service), so a session goes stale in 15 minutes with no
   refresh mechanism anywhere in the platform yet. `AuthRequiredScreen` (replacing
   `PinScreen`) is the entire mitigation on ATT's side: any `401` sends the user back to MM OS
   to relaunch, rather than presenting a broken app or a local re-auth form that doesn't
   exist any more. This is a platform-wide characteristic, not something specific to ATT.

## Not done

1. **Item Code Studio** — does not exist; see the note at the top of this document. When it
   is built, it will need: the three structural rules from `docs/05` (a single
   `/api/admin/*` write prefix behind one guard, a `public_paths` allowlist for the public
   lookup and nothing else, and a read-only Postgres role for the public path per
   `deploy/postgres/init.sql`), `viewer`/`admin` roles, and the same `mmos-client-py` wiring
   pattern now proven working in ATT — `ATT_Platform/backend/mmos_integration.py` on branch
   `mmos-retrofit` is a usable template for the auth half of that build (the dual-mode
   split and the Postgres role are the genuinely new parts it doesn't cover).
2. **ERPNext / Twenty CRM configuration** — out of scope for this run (redirected to ATT
   Platform only); not attempted, and no claims made about it here.
3. **Registering `att` in a live MM OS and obtaining a real `MMOS_SERVICE_KEY`** — no
   reachable MM OS instance in this sandbox; exact commands for a human are in
   `## Assumptions` #1.
4. **Per-provider `report_usage()` token counts are implemented against each provider's
   documented response shape but not exercised against a real Anthropic/Gemini/Ollama call**
   — no API key or local Ollama instance available here. The plumbing itself (accumulate →
   ship on heartbeat → visible via `/api/admin/llm`) was proven live against the stub MM OS
   with synthetic `report_usage()` calls (see `## How to verify`).
5. **The real 60-second wall-clock revocation SLA** was proven via the same deterministic
   `poller.poll_once()` mechanism this repo's own client-library tests and
   `examples/echo-service/README.md` use, not by an actual 60-second wait —
   `examples/echo-service/README.md` already did that live wait once for this exact,
   unmodified client library; re-proving the same library's timer here would be redundant,
   not additional evidence.
6. **No production deployment config** (Coolify env vars, real `MMOS_SERVICE_KEY` in a real
   environment) — deployment access wasn't part of this task.

## How to verify

```bash
cd "C:/Users/Anura/OneDrive/Desktop/ATT_Platform"
git log --oneline -3                 # 7a60e4a, 2be2337 on branch mmos-retrofit, atop b794201
git status                           # clean

# 0. The four boot cases (the fail-closed contract from ## Deviations #5) — a dedicated,
#    committed script, since there's no existing pytest suite in this repo to extend.
venv/Scripts/python.exe scripts/verify_boot_modes.py
# -> PASS  neither var set -> refuse  (exit=1)
# -> PASS  ATT_DEV_NO_AUTH=1 only -> boots (dev)  (exit=0)
# -> PASS  MMOS_SERVICE_KEY only -> boots (real)  (exit=0)
# -> PASS  both set -> refuse  (exit=1)
# -> == 4 passed, 0 failed ==

# 1. Documented local-dev path: boots and serves everything, with no MM OS reachable, but
#    only because ATT_DEV_NO_AUTH=1 was explicitly set (not merely because a key is absent)
ATT_DEV_NO_AUTH=1 venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# -> logs: "[mmos] ATT_DEV_NO_AUTH=1 -- running WITHOUT MM OS auth, ON PURPOSE. ..."
# -> curl http://127.0.0.1:8000/            -> 200, full SPA HTML (embed.js tag included)
# -> curl http://127.0.0.1:8000/api/runs    -> 200 (dev-fallback synthetic admin user)
# -> curl http://127.0.0.1:8000/api/settings -> "auth":{"mmos_enabled":false} (drives the
#    frontend's red "LOCAL DEV MODE" banner)
# -> running with NEITHER MMOS_SERVICE_KEY NOR ATT_DEV_NO_AUTH set refuses to start instead
#    (uvicorn exits non-zero immediately, before binding a port) — this is the actual fix

# 2. Both PIN gates gone (ATT's; Item Code Studio's doesn't exist to check)
grep -rni pin backend frontend/src
# -> only comments explaining the removal, no pin_gate/PinIn/pin_enabled/X-ATT-Pin code

# 3. Frontend builds clean
cd frontend && npx tsc -b && npm run build && cd ..
```

**4. Full auth wiring, proven against a throwaway stub MM OS** — the same `stub_mmos.py`
`examples/echo-service` uses in this repo, with that same `echo-service` as the second,
cross-rejecting service (per this task's own substitution for Item Code Studio). Run from
this repo (needs both repos on disk at their normal paths):

```python
"""Run with: <ATT venv>/python.exe this_file.py"""
import os, sys, time
MMOS_REPO = r"C:\Users\Anura\OneDrive\Desktop\MM OS"
ATT_REPO = r"C:\Users\Anura\OneDrive\Desktop\ATT_Platform"
STUB_PORT = 8199
os.environ["STUB_MMOS_PORT"] = str(STUB_PORT)
os.environ["MMOS_SERVICE_KEY"] = "dev-demo-key-echo"
sys.path.insert(0, os.path.join(MMOS_REPO, "examples", "echo-service"))
sys.path.insert(0, os.path.join(MMOS_REPO, "packages", "mmos-client-py"))
import main as echo_main            # starts the ONE shared stub_mmos on STUB_PORT
import stub_mmos
time.sleep(0.5)
os.environ["MMOS_SERVICE_KEY"] = "dev-demo-key-att"
os.environ["MMOS_OS_URL"] = f"http://127.0.0.1:{STUB_PORT}"
os.environ["MMOS_ISSUER"] = stub_mmos.ISSUER
os.environ["MMOS_SERVICE_SLUG"] = "att"
sys.path.insert(0, ATT_REPO)
import backend.main as att_main
import backend.mmos_integration as att_mmos
import httpx
from fastapi.testclient import TestClient
STUB_URL = f"http://127.0.0.1:{STUB_PORT}"

with TestClient(att_main.app) as att, TestClient(echo_main.app) as echo:
    att_viewer = stub_mmos.mint(slug="att", roles=["viewer"], sub="user:viewer1")
    att_admin = stub_mmos.mint(slug="att", roles=["admin", "viewer"], sub="user:admin1")
    echo_viewer = stub_mmos.mint(slug="echo", roles=["viewer"], sub="user:echoer")
    auth = lambda t: {"Authorization": f"Bearer {t}"}

    assert att.get("/_mmos/health").status_code == 200
    assert att.get("/api/runs").status_code == 401                       # no token
    assert att.get("/api/runs", headers=auth(att_viewer)).status_code == 200
    r = att.post("/api/runs", headers=auth(att_viewer), data={"name": "x", "use_llm": "false"},
                 files={"exim_files": ("f.xlsx", b"x", "application/octet-stream")})
    assert r.status_code == 403 and r.json()["need"] == "admin"          # viewer blocked
    r = att.post("/api/runs", headers=auth(att_admin), data={"name": "x", "use_llm": "false"},
                 files={"exim_files": ("f.xlsx", b"x", "application/octet-stream")})
    assert r.status_code not in (401, 403)                               # admin allowed

    # cross-service rejection -- the actual security property, both directions
    r = att.get("/api/runs", headers=auth(echo_viewer))
    assert r.status_code == 401 and r.json()["error"] == "bad_audience"
    r = echo.get("/api/whoami", headers=auth(att_viewer))
    assert r.status_code == 401 and r.json()["error"] == "bad_audience"
    assert echo.get("/api/whoami", headers=auth(echo_viewer)).status_code == 200

    # revocation within one poll (mechanism proven live for 60s once already, in
    # examples/echo-service/README.md, against this same unmodified client library)
    assert att.get("/api/runs", headers=auth(att_viewer)).status_code == 200
    httpx.post(f"{STUB_URL}/_demo/revoke", params={"sub": "user:viewer1"})
    assert att_mmos.mmos.poller.poll_once() is True
    r = att.get("/api/runs", headers=auth(att_viewer))
    assert r.status_code == 401 and r.json()["error"] == "revoked"

    # confirm the client polls the FIXED path (B1's bug fix), not the doc's stale one
    import backend.vendor.mmos_client._denylist as dl, inspect
    src = inspect.getsource(dl)
    assert '"/api/agent/revocations"' in src

    # LLM kill switch -> llm_guard() actually 503s the entry point
    httpx.post(f"{STUB_URL}/_demo/llm", params={"enabled": False})
    att_mmos.mmos.heartbeat.beat_once()
    r = att.post("/api/runs", headers=auth(att_admin), data={"name": "y", "use_llm": "true"},
                 files={"exim_files": ("f.xlsx", b"x", "application/octet-stream")})
    assert r.status_code == 503 and r.json()["error"] == "llm_disabled"

print("19/19 checks passed")
```

Actually run, verbatim result: **19 passed, 0 failed** — health, unauthenticated 401, viewer
read 200, viewer write 403 (`need:"admin"`), admin write past the gate, `bad_audience`
rejection in both directions between `att` and `echo`, each service accepting its own token,
revocation blocking access within one poll, the poller confirmed on the fixed
`/api/agent/revocations` path (both by behavior and by source inspection), the LLM kill
switch flipping the cached flag via `heartbeat.beat_once()`, and `llm_guard()` correctly
503-ing `POST /api/runs` when `use_llm=true` and the kill switch is off.

**Re-run after the fail-closed correction (commit `7a60e4a`), to confirm no regression:**
same script, same `MMOS_SERVICE_KEY`-only environment it always used (never
`ATT_DEV_NO_AUTH`) — **19 passed, 0 failed**, identical to the first run. Plus
`scripts/verify_boot_modes.py`'s own **4 passed, 0 failed** for the four boot cases
themselves (`## How to verify` step 0).
