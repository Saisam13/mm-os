"""echo-service — the ~100-line proof that mmos-client-py implements docs/05's contract.

Runs a tiny stub of MM OS in a background thread so this file is runnable standalone with
no other MM OS process anywhere. See README.md for the one command.

Routes:
    GET  /                    public
    GET  /api/public/ping     public (prefix-allowlisted)
    GET  /api/whoami          authenticated: echoes the caller's own claims
    POST /api/admin/note      admin-only write
    POST /api/llm/echo        llm_guard() + report_usage()
"""
from __future__ import annotations

import os
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "packages" / "mmos-client-py"))

import uvicorn
from fastapi import Depends, FastAPI

import stub_mmos
from mmos_client import MMOS, CurrentUser, llm_guard, report_usage, require_role

STUB_PORT = int(os.environ.get("STUB_MMOS_PORT", "8199"))
STUB_URL = f"http://127.0.0.1:{STUB_PORT}"


def _run_stub() -> None:
    uvicorn.run(stub_mmos.app, host="127.0.0.1", port=STUB_PORT, log_level="warning")


threading.Thread(target=_run_stub, daemon=True).start()
time.sleep(0.5)  # let the stub bind before the client's first JWKS/heartbeat call

app = FastAPI(title="echo-service")

mmos = MMOS(
    slug="echo",
    os_url=STUB_URL,
    issuer=stub_mmos.ISSUER,  # only needed because this demo mints against a stub issuer
    service_key=os.environ.get("MMOS_SERVICE_KEY", "dev-demo-key"),
    public_paths=["/", "/api/public", "/_demo"],  # /_demo is this example's own bootstrap helper
    version="0.1.0",
)
mmos.install(app)


@app.get("/")
def root():
    return {"service": "echo", "public": True}


@app.get("/api/public/ping")
def ping():
    return {"pong": True}


@app.get("/api/whoami")
def whoami(user: CurrentUser = Depends(mmos.user)):
    return {
        "sub": user.sub,
        "employee_code": user.employee_code,
        "name": user.name,
        "roles": user.roles,
    }


@app.post("/api/admin/note")
def write_note(payload: dict, user: CurrentUser = Depends(require_role("admin"))):
    return {"ok": True, "written_by": user.employee_code, "note": payload.get("note", "")}


@app.post("/api/llm/echo")
def llm_echo(payload: dict, user: CurrentUser = Depends(mmos.user)):
    llm_guard()
    text = str(payload.get("text", ""))
    report_usage(requests=1, input_tokens=len(text.split()), output_tokens=len(text.split()))
    return {"echo": text}


@app.get("/_demo/mint")
def demo_mint(roles: str = "viewer", sub: str = "user:demo-1"):
    """Demo-only convenience so this service can be exercised with curl alone. A real
    MM OS-facing service never exposes a route like this."""
    return stub_mmos._demo_mint(roles=roles, sub=sub)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8090")))
