# 05 · Service integration contract

Everything a service must do to join MM OS. Deliberately small — five things — because a
contract nobody can implement in an afternoon gets bypassed.

## The contract

| # | Requirement | Why |
|---|---|---|
| 1 | Mount the MM OS client middleware | verifies tokens, holds the deny-list, exposes `/_mmos/accept` |
| 2 | Serve `GET /_mmos/health` | registry health dot, and it proves the service key works |
| 3 | Send a heartbeat every 5 minutes | liveness, LLM visibility, kill-switch pickup |
| 4 | Include `embed.js` in the page shell | the Back-to-MM-OS bar and app switcher |
| 5 | Put every write endpoint under one guarded prefix | the dual-mode safety rule below |

## Python service (the ATT / Item Code Studio pattern)

```python
from fastapi import FastAPI, Depends
from mmos_client import MMOS, require_role, CurrentUser

app = FastAPI()

mmos = MMOS(
    slug="itemcode",
    os_url="https://os.m-mines.com",
    service_key=os.environ["MMOS_SERVICE_KEY"],
    public_paths=["/", "/lookup", "/api/public"],   # anonymous surface, explicit
)
mmos.install(app)      # adds /_mmos/accept, /_mmos/health, deny-list poller, heartbeat loop

@app.get("/api/public/lookup")                      # no auth: the public code checker
def lookup(q: str): ...

@app.get("/api/admin/items")
def list_items(user: CurrentUser = Depends(mmos.user)): ...

@app.post("/api/admin/items")
def create_item(payload: ItemIn, user: CurrentUser = Depends(require_role("admin"))):
    ...   # user.employee_code, user.department, user.band available for the audit row
```

`require_role("admin")` returns `403` with `{"error":"role_required","need":"admin","have":["viewer"]}`.
The service does not know or care how that role was decided.

### Reporting LLM usage

```python
from mmos_client import llm_guard, report_usage

@app.post("/api/admin/match")
def match(rows: list[str], user: CurrentUser = Depends(require_role("admin"))):
    llm_guard()                       # raises 503 llm_disabled if MM OS turned it off
    result = matcher.run(rows)
    report_usage(requests=1, input_tokens=result.in_tok, output_tokens=result.out_tok)
    return result
```

`llm_guard()` reads a cached flag refreshed by the heartbeat — no network call in the
request path. `report_usage` accumulates in memory and ships with the next heartbeat, so
losing MM OS costs you counters, never requests.

For the full per-feature contract — how a service fetches its allowed AI policy
(providers/models + kill switch + a `config_version` to poll) and reports per-feature usage,
and the hard boundary that **provider API keys stay in the service and MM OS holds none** —
see **[docs/15 · LLM control plane](15-llm-control-plane.md)**.

## Frontend

```html
<script src="https://os.m-mines.com/embed.js" defer></script>
```

That is the whole integration. The bar reads the service session, renders in a shadow root,
and needs no configuration — it learns the current service from the hostname.

## Dual-mode services: the structural rule

Item Code Studio is one app with a public lookup and an admin console. That is the chosen
design, and it has exactly one failure mode: a routing mistake exposes item-code creation to
anyone. Discipline does not prevent that; structure does.

**Three rules, non-negotiable:**

1. **One prefix for writes.** Every mutating endpoint lives under `/api/admin/*`. A single
   middleware guards the prefix. There is no mutating endpoint anywhere else, so a new route
   cannot accidentally be born unprotected — it is either under the guard or it cannot write.
2. **The anonymous surface is an allowlist, never a denylist.** `public_paths` enumerates
   what is open. Anything not listed requires a token. A forgotten route fails closed.
3. **The public surface reads through a read-only Postgres role.** Even a total logic
   failure on the public path cannot write, because the database connection it holds has no
   `INSERT`, `UPDATE` or `DELETE` grant.

```sql
CREATE ROLE itemcode_public LOGIN PASSWORD '…';
GRANT CONNECT ON DATABASE itemcode TO itemcode_public;
GRANT USAGE ON SCHEMA public TO itemcode_public;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO itemcode_public;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO itemcode_public;
```

Rule 3 is the one that actually saves you, because it holds even when rules 1 and 2 are
broken by a future edit.

## Registering a new service

```bash
# 1. create it in MM OS admin (or via API) and take the key — shown once
curl -X POST https://os.m-mines.com/api/admin/services \
  -H 'Content-Type: application/json' -b mmos_session=… \
  -d '{"slug":"analytics","name":"Analytics Hub","base_url":"https://analytics.m-mines.com",
       "category":"commercial","icon":"bar-chart","launch_mode":"handoff"}'

# 2. define its roles
curl -X POST https://os.m-mines.com/api/admin/services/analytics/roles \
  -d '{"key":"viewer","name":"Viewer","is_default":true}'

# 3. put MMOS_SERVICE_KEY in the Coolify env for that container, deploy
# 4. grant people access — the tile appears on their homepage, no redeploy
```

Step 4 is the payoff: access changes are data, not deployments.

## Non-Python and third-party services

| Service | Integration |
|---|---|
| **ERPNext** (Frappe Cloud) | Google social login pointed at the same Workspace, so it is the same identity. MM OS holds only the tile and the grant. Back-link added via **Navbar Settings → custom navbar items**. Token handoff is not used — Frappe owns its own session. |
| **Twenty CRM** (self-hosted) | Google auth, plus the `embed.js` tag in its build. |
| **Node / other runtimes** | Verify the JWT with any standard JWKS library (`jose`), poll `/api/revocations`, POST the heartbeat. The contract is HTTP, not Python — `mmos-client-py` is a convenience, not the interface. |

## Checklist before a service is called integrated

- [ ] verifies `aud` — confirm a token minted for another slug is rejected
- [ ] rejects an expired token (set skew to 0 and test)
- [ ] rejects a revoked subject within 60s (remove a grant and watch)
- [ ] `/_mmos/health` returns 200 and the registry dot goes green
- [ ] heartbeat visible in `/api/admin/llm` (or shows `unreported` on purpose)
- [ ] OS bar renders and Back-to-MM-OS works
- [ ] no mutating endpoint outside `/api/admin/*`
- [ ] public path list is complete and minimal, public DB role is read-only
