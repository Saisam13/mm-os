# mmos-client-py

The drop-in MM OS auth client for Python services. Verifies tokens, polls the deny-list,
sends the heartbeat, gates the LLM control plane. Full contract: `docs/05-service-integration.md`.

## Integration

```python
import os
from fastapi import FastAPI, Depends
from mmos_client import MMOS, require_permission, CurrentUser, llm_guard, report_usage

app = FastAPI()

mmos = MMOS(
    slug="itemcode",
    os_url="https://m-mines.in",
    service_key=os.environ["MMOS_SERVICE_KEY"],
    public_paths=["/", "/lookup", "/api/public"],   # anything else needs a token
)
mmos.install(app)   # adds /_mmos/accept, /_mmos/health, deny-list poller, heartbeat loop

@app.get("/api/public/lookup")
def lookup(q: str): ...

@app.get("/api/admin/items")
def list_items(user: CurrentUser = Depends(mmos.user)): ...

@app.post("/api/admin/items")
def create_item(payload: dict, user: CurrentUser = Depends(require_permission("items.create", max_authority_age_seconds=300))):
    llm_guard()  # 503 llm_disabled if MM OS turned this service's LLM off
    result = do_it(payload)
    report_usage(requests=1, input_tokens=result.in_tok, output_tokens=result.out_tok)
    return result
```

`public_paths` is an allowlist. Every other path requires a verified token. Use explicit
permissions for actions, then check ownership, department and workflow eligibility against
the requested object. A role label or `platform_admin` never overrides an action guard.
`require_role` remains available for legacy integrations and is not a substitute for
permission enforcement.

During an MMOS outage, existing tokens remain usable only until their expiry and while
the last successful revocation snapshot is at most 900 seconds old. Sensitive actions can
require a shorter age, as in the 300-second example above. These bounds include actual
grant expiry; there is no indefinite or automatic local-login fallback. A cold service
cannot establish trust during an outage.

Set `MMOS_CACHE_DIRECTORY` to a private, persistent, service-specific volume to preserve
public keys and revocations across restarts. The cache stores no JWT or service key.
Known public keys expire after 24 hours without successful refresh; unknown keys fail
closed. This does not extend token or authority validity. Production containers must
configure and test the mounted directory and access permissions. `/_mmos/health` exposes
authority age and whether persistence is configured. `llm_guard()` reads the cached flag
and makes no request-time network call.

Not installed into the shared venv on purpose (see `handoff/a4-integration.md`) — tests and
`examples/echo-service` reach it via `conftest.py` / `sys.path`, exactly as a real consumer
would reach it via `pip install mmos-client-py`.
