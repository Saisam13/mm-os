# mmos-client-py

The drop-in MM OS auth client for Python services. Verifies tokens, polls the deny-list,
sends the heartbeat, gates the LLM control plane. Full contract: `docs/05-service-integration.md`.

## Integration

```python
import os
from fastapi import FastAPI, Depends
from mmos_client import MMOS, require_role, CurrentUser, llm_guard, report_usage

app = FastAPI()

mmos = MMOS(
    slug="itemcode",
    os_url="https://os.m-mines.com",
    service_key=os.environ["MMOS_SERVICE_KEY"],
    public_paths=["/", "/lookup", "/api/public"],   # anything else needs a token
)
mmos.install(app)   # adds /_mmos/accept, /_mmos/health, deny-list poller, heartbeat loop

@app.get("/api/public/lookup")
def lookup(q: str): ...

@app.get("/api/admin/items")
def list_items(user: CurrentUser = Depends(mmos.user)): ...

@app.post("/api/admin/items")
def create_item(payload: dict, user: CurrentUser = Depends(require_role("admin"))):
    llm_guard()  # 503 llm_disabled if MM OS turned this service's LLM off
    result = do_it(payload)
    report_usage(requests=1, input_tokens=result.in_tok, output_tokens=result.out_tok)
    return result
```

That's the whole integration. `public_paths` is an allowlist — anything not listed requires
a valid token and fails closed. `require_role` returns `403
{"error":"role_required","need":"admin","have":[...]}`. If MM OS goes down, already-verified
callers keep being served against the last known deny-list; `llm_guard()` never makes a
network call, it reads the flag the last heartbeat cached.

Not installed into the shared venv on purpose (see `handoff/a4-integration.md`) — tests and
`examples/echo-service` reach it via `conftest.py` / `sys.path`, exactly as a real consumer
would reach it via `pip install mmos-client-py`.
