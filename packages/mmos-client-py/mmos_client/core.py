"""The MMOS client: `mmos = MMOS(...)`, `mmos.install(app)`, `Depends(mmos.user)`,
`require_role(...)`, `llm_guard()`, `report_usage(...)`.

See packages/mmos-client-py/README.md for the integration copy-paste and
handoff/a4-integration.md for what is and isn't covered.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import http_exception_handler as _default_http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ._denylist import DenyList, DenyListPoller
from ._heartbeat import Heartbeat, UsageAccumulator
from ._jwks import JWKSCache
from ._verify import TokenError, verify_token

logger = logging.getLogger("mmos_client")

_ALWAYS_PUBLIC = {"/_mmos/accept", "/_mmos/session", "/_mmos/health"}

_ACCEPT_HTML = """<!doctype html>
<meta charset="utf-8">
<title>Signing in…</title>
<body style="font-family:system-ui,sans-serif;color:#48596A;background:#F0F4FA">
<p id="mmos-msg">Signing in…</p>
<script>
(function () {
  var frag = window.location.hash || "";
  var m = frag.match(/token=([^&]+)/);
  var msg = document.getElementById("mmos-msg");
  if (!m) { msg.textContent = "No token in the URL."; return; }
  var token = decodeURIComponent(m[1]);
  fetch("/_mmos/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ token: token })
  }).then(function (r) {
    if (!r.ok) throw new Error("rejected");
    history.replaceState(null, "", window.location.pathname);
    window.location.replace("/");
  }).catch(function () {
    history.replaceState(null, "", window.location.pathname);
    msg.textContent = "Sign-in failed. Ask MM OS to send a new link.";
  });
})();
</script>
</body>
"""


@dataclass(frozen=True)
class CurrentUser:
    """The verified caller, shaped from the token claims in docs/03-api-contract.md."""

    sub: str
    employee_code: str
    email: str
    name: str
    department: str | None
    division: str | None
    band: str | None
    approval_level: str | None
    roles: list[str] = field(default_factory=list)
    platform_admin: bool = False
    jti: str = ""
    exp: int = 0

    @classmethod
    def from_claims(cls, claims: dict) -> "CurrentUser":
        return cls(
            sub=claims.get("sub", ""),
            employee_code=claims.get("emp", ""),
            email=claims.get("email", ""),
            name=claims.get("name", ""),
            department=claims.get("dept"),
            division=claims.get("division"),
            band=claims.get("band"),
            approval_level=claims.get("approval_level"),
            roles=list(claims.get("roles") or []),
            platform_admin=bool(claims.get("platform_admin", False)),
            jti=claims.get("jti", ""),
            exp=int(claims.get("exp") or 0),
        )


# The most recently constructed MMOS instance. `require_role`, `llm_guard` and
# `report_usage` are free functions per the contract (`llm_guard()` takes no arguments), so
# they resolve against this. One MMOS instance per process is the supported shape — see
# `## Assumptions` in the handoff.
_ACTIVE: "MMOS | None" = None


class MMOS:
    def __init__(
        self,
        *,
        slug: str,
        os_url: str,
        service_key: str,
        public_paths: list[str] | None = None,
        issuer: str | None = None,
        version: str = "0.0.0",
        poll_after_seconds: int = 60,
        heartbeat_seconds: int = 300,
        jwks_min_refresh_seconds: int = 60,
        clock_skew_seconds: int = 60,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        llm_key_present: bool = False,
        cookie_name: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.slug = slug
        self.os_url = os_url.rstrip("/")
        self.service_key = service_key
        self.public_paths = list(public_paths or [])
        self.issuer = issuer or self.os_url
        self.version = version
        self.clock_skew_seconds = clock_skew_seconds
        self.cookie_name = cookie_name or f"{slug}_mmos_at"

        # follow_redirects: MM OS is fronted by a proxy that 302-redirects http→https
        # (HTTPS-everywhere). The JWKS/revocations fetches must transparently follow that
        # redirect, or a service configured with an http os_url gets the 302 body instead of
        # the key set and fails every token with unknown_kid. httpx defaults this to False.
        self._http = http_client or httpx.Client(base_url=self.os_url, follow_redirects=True)
        self._jwks = JWKSCache(
            f"{self.os_url}/.well-known/jwks.json",
            http_client=self._http,
            min_refresh_seconds=jwks_min_refresh_seconds,
        )
        self._denylist = DenyList()
        self.poller = DenyListPoller(
            http_client=self._http,
            service_key=service_key,
            denylist=self._denylist,
            default_interval_seconds=poll_after_seconds,
        )
        self._usage = UsageAccumulator()
        self.heartbeat = Heartbeat(
            http_client=self._http,
            service_key=service_key,
            version=version,
            usage=self._usage,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_key_present=llm_key_present,
            interval_seconds=heartbeat_seconds,
        )

        global _ACTIVE
        _ACTIVE = self

    # ── token plumbing ──────────────────────────────────────────────────
    def _extract_token(self, request: Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return request.cookies.get(self.cookie_name)

    def _verify(self, token: str) -> dict:
        return verify_token(
            token,
            jwks_cache=self._jwks,
            issuer=self.issuer,
            audience=self.slug,
            skew_seconds=self.clock_skew_seconds,
            denylist=self._denylist,
        )

    def user(self, request: Request) -> CurrentUser:
        """`Depends(mmos.user)` — the one dependency every guarded route needs."""
        claims = getattr(request.state, "mmos_claims", None)
        if claims is None:
            token = self._extract_token(request)
            if not token:
                raise HTTPException(status_code=401, detail={"error": "missing_token"})
            try:
                claims = self._verify(token)
            except TokenError as exc:
                raise HTTPException(status_code=401, detail={"error": exc.reason})
        return CurrentUser.from_claims(claims)

    # ── allowlist ────────────────────────────────────────────────────────
    def _is_public(self, path: str) -> bool:
        if path in _ALWAYS_PUBLIC:
            return True
        for p in self.public_paths:
            if p == "/":
                if path == "/":
                    return True
                continue
            if path == p or path.startswith(p.rstrip("/") + "/"):
                return True
        return False

    # ── ASGI middleware: the allowlist actually fails closed here ──────────
    async def _dispatch(self, request: Request, call_next):
        token = self._extract_token(request)
        claims = None
        error = None
        if token:
            try:
                claims = self._verify(token)
            except TokenError as exc:
                error = exc.reason
        request.state.mmos_claims = claims
        request.state.mmos_error = error

        if not self._is_public(request.url.path) and claims is None:
            reason = error or "missing_token"
            return JSONResponse({"error": reason}, status_code=401)
        return await call_next(request)

    # ── startup-time audit: a forgotten route should be loud, not silent ──
    def _audit_routes(self, app: FastAPI) -> None:
        for route in getattr(app, "routes", []):
            path = getattr(route, "path", None)
            if path is None or self._is_public(path):
                continue
            guarded = False
            dependant = getattr(route, "dependant", None)
            for dep in _iter_dependencies(dependant):
                call = getattr(dep, "call", None)
                if call is None:
                    continue
                if getattr(call, "__self__", None) is self:
                    guarded = True
                    break
                if getattr(call, "_mmos_role_guard", False):
                    guarded = True
                    break
            if not guarded:
                logger.warning(
                    "mmos: %s is not in public_paths and has no mmos.user/require_role "
                    "dependency; it is protected only by the allowlist middleware.",
                    path,
                )

    # ── wiring ──────────────────────────────────────────────────────────
    def install(self, app: FastAPI, *, start_background: bool = True) -> None:
        mmos = self

        @app.get("/_mmos/accept", include_in_schema=False)
        def _accept() -> HTMLResponse:
            return HTMLResponse(_ACCEPT_HTML)

        @app.post("/_mmos/session", include_in_schema=False)
        async def _session(request: Request, response: Response):
            body = await request.json()
            token = body.get("token", "")
            try:
                mmos._verify(token)
            except TokenError as exc:
                raise HTTPException(status_code=401, detail={"error": exc.reason})
            response.set_cookie(
                mmos.cookie_name,
                token,
                httponly=True,
                secure=True,
                samesite="lax",
                path="/",
            )
            return {"ok": True}

        @app.get("/_mmos/health", include_in_schema=False)
        def _health():
            return {"ok": True, "slug": mmos.slug, "version": mmos.version}

        app.add_middleware(BaseHTTPMiddleware, dispatch=self._dispatch)
        app.add_exception_handler(HTTPException, _flat_http_exception_handler)

        @app.on_event("startup")
        def _on_startup():
            mmos._audit_routes(app)
            if start_background:
                mmos.poller.start()
                mmos.heartbeat.start()


async def _flat_http_exception_handler(request: Request, exc: HTTPException):
    """The contract's error shapes (`{"error":"role_required",...}`, `{"error":"llm_disabled"}`)
    are flat JSON, not FastAPI's default `{"detail": {...}}` envelope."""
    if isinstance(exc.detail, dict):
        return JSONResponse(exc.detail, status_code=exc.status_code, headers=getattr(exc, "headers", None))
    return await _default_http_exception_handler(request, exc)


def require_role(role: str):
    """`Depends(require_role("admin"))` — 403 `{"error":"role_required","need":...,"have":[...]}`."""

    def _dep(user: CurrentUser = Depends(_active_user_dependency)) -> CurrentUser:
        if role not in user.roles:
            raise HTTPException(
                status_code=403,
                detail={"error": "role_required", "need": role, "have": user.roles},
            )
        return user

    _dep._mmos_role_guard = True
    return _dep


def _active_user_dependency(request: Request) -> CurrentUser:
    if _ACTIVE is None:
        raise HTTPException(status_code=500, detail={"error": "mmos_not_installed"})
    return _ACTIVE.user(request)


def llm_guard() -> None:
    """Raises 503 `{"error":"llm_disabled"}` if MM OS turned this service's LLM access off.
    Reads the flag cached by the last heartbeat — no network call in the request path."""
    if _ACTIVE is None or not _ACTIVE.heartbeat.llm_enabled:
        raise HTTPException(status_code=503, detail={"error": "llm_disabled"})


def report_usage(*, requests: int = 0, input_tokens: int = 0, output_tokens: int = 0) -> None:
    """Accumulates in memory; ships on the next heartbeat. Losing MM OS costs counters,
    never requests."""
    if _ACTIVE is None:
        return
    _ACTIVE._usage.add(requests=requests, input_tokens=input_tokens, output_tokens=output_tokens)


def _iter_dependencies(dependant):
    if dependant is None:
        return
    seen = set()
    stack = [dependant]
    while stack:
        d = stack.pop()
        if id(d) in seen:
            continue
        seen.add(id(d))
        yield d
        for sub in getattr(d, "dependencies", []) or []:
            stack.append(sub)
