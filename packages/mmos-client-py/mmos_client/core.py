"""The MMOS client: `mmos = MMOS(...)`, `mmos.install(app)`, `Depends(mmos.user)`,
`require_role(...)`, `llm_guard()`, `report_usage(...)`.

See packages/mmos-client-py/README.md for the integration copy-paste and
handoff/a4-integration.md for what is and isn't covered.
"""
from __future__ import annotations

import logging
import hashlib
import os
import time
from contextlib import asynccontextmanager
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
from ._state import StateStore

logger = logging.getLogger("mmos_client")

_ALWAYS_PUBLIC = {"/_mmos/accept", "/_mmos/session", "/_mmos/health", "/_mmos/logout"}

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
  history.replaceState(null, "", window.location.pathname + window.location.search);
  // Read the ?next= query param so the caller can control where we land after
  // sign-in. Defaults to "/" if absent. Only accept same-origin paths.
  var params = new URLSearchParams(window.location.search);
  var next = params.get("next") || "/";
  if (!next.startsWith("/") || next.startsWith("//")) { next = "/"; }
  fetch("/_mmos/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ token: token })
  }).then(function (r) {
    if (!r.ok) throw new Error("rejected");
    history.replaceState(null, "", window.location.pathname);
    var dest = new URL(next, window.location.origin);
    window.location.replace(dest.pathname + dest.search);
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
    permissions: list[str] = field(default_factory=list)
    policy_version: str | None = None
    iat: int = 0
    actor_type: str = "human"
    permissions_present: bool = False

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
            permissions=list(claims.get("permissions") or []),
            policy_version=claims.get("pv"),
            iat=int(claims.get("iat") or 0),
            actor_type=claims.get('actor_type','human'),
            permissions_present='permissions' in claims,
        )


# The most recently constructed MMOS instance. `require_role`, `llm_guard` and
# `report_usage` are free functions per the contract (`llm_guard()` takes no arguments), so
# they resolve against this. One MMOS instance per process is the supported shape — see
# `## Assumptions` in the handoff.
_ACTIVE: "MMOS | None" = None

# The `iss` claim MM OS actually signs (backend/app/config.py). It is an IDENTITY, not an
# address: MM OS stamps this string whatever hostname you reached it on. Defaulting it to
# `os_url` — as this client used to — silently couples token verification to the URL, so the
# day a service is repointed at a different hostname (a DNS move, a Coolify sslip.io
# fallback) every token starts failing on issuer with nothing in the logs to say why. That
# is half of the 7 Sep outage; see docs/16-decisions.md D-2026-09-07-2.
DEFAULT_ISSUER = "https://m-mines.in"


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
        state_directory: str | None = None,
        max_offline_seconds: int = 900,
    ):
        if not 0 <= clock_skew_seconds <= 60 or not 0 < max_offline_seconds <= 900:
            raise ValueError("Clock skew must be at most 60s and offline authority at most 900s")
        self.slug = slug
        self.os_url = os_url.rstrip("/")
        self.service_key = service_key
        self.public_paths = list(public_paths or [])
        self.issuer = issuer or DEFAULT_ISSUER
        self.version = version
        self.clock_skew_seconds = clock_skew_seconds
        self.cookie_name = cookie_name or f"{slug}_mmos_at"
        self.max_offline_seconds = max_offline_seconds
        self._cold_poll_attempted = False
        directory = state_directory or os.environ.get("MMOS_CACHE_DIRECTORY")
        namespace = hashlib.sha256(f"{self.issuer}|{self.os_url}|{slug}".encode()).hexdigest()[:24]
        store = StateStore(directory, namespace) if directory else None
        self.persistent_trust_cache = store is not None

        # follow_redirects: MM OS is fronted by a proxy that 302-redirects http→https
        # (HTTPS-everywhere). The JWKS/revocations fetches must transparently follow that
        # redirect, or a service configured with an http os_url gets the 302 body instead of
        # the key set and fails every token with unknown_kid. httpx defaults this to False.
        self._http = http_client or httpx.Client(base_url=self.os_url, follow_redirects=True)
        self._jwks = JWKSCache(
            f"{self.os_url}/.well-known/jwks.json",
            http_client=self._http,
            min_refresh_seconds=jwks_min_refresh_seconds,
            state_store=store,
        )
        self._denylist = DenyList(state_store=store)
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
        claims = verify_token(
            token,
            jwks_cache=self._jwks,
            issuer=self.issuer,
            audience=self.slug,
            skew_seconds=self.clock_skew_seconds,
            denylist=self._denylist,
        )
        if self._denylist.last_success_at is None and not self._cold_poll_attempted:
            self._cold_poll_attempted = True
            self.poller.poll_once()
        age = self.authority_age_seconds
        if age is None or not 0 <= age <= self.max_offline_seconds:
            raise TokenError("authority_unavailable")
        if self._denylist.is_revoked(sub=claims["sub"], jti=claims["jti"], iat=claims["iat"]):
            raise TokenError("revoked")
        return claims

    @property
    def authority_age_seconds(self) -> float | None:
        last = self._denylist.last_success_at
        return time.time() - last if last is not None else None

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

    # ── pointing check ───────────────────────────────────────────────────
    def probe_os(self) -> tuple[bool, str | None]:
        """Is this service actually pointed at a live MM OS?

        The 7 Sep outage was a pointing failure, not a code failure: the hostname the
        services were configured with stopped resolving to the VPS and nothing noticed until
        a person tried to sign in. This fetches the key set the same way verification does,
        so a wrong pointer is a readable health field instead of a redirect loop.

        Returns `(reachable, detail)`; `detail` is None when reachable.
        """
        try:
            resp = self._http.get("/.well-known/jwks.json", timeout=5.0)
        except Exception as exc:  # noqa: BLE001 — a health probe never raises
            return False, f"{type(exc).__name__}: {exc}"

        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"

        content_type = resp.headers.get("content-type", "")
        if "json" not in content_type:
            # The precise shape of the outage: a parked host, or MM OS's own SPA catch-all,
            # answers 200 with HTML. Saying so beats a JSON decode error.
            return False, f"expected JSON, got {content_type or 'no content-type'}"

        try:
            keys = resp.json().get("keys")
        except Exception:  # noqa: BLE001
            return False, "response was not valid JSON"

        if not isinstance(keys, list) or not keys:
            return False, "key set is empty"
        return True, None

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
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            # Explicit bearer clients do not rely on ambient cookies. Session bootstrap
            # accepts its own origin only; the handoff page executes on that origin.
            cookie_auth = request.cookies.get(self.cookie_name) and not request.headers.get("authorization")
            if cookie_auth or request.url.path == "/_mmos/session":
                if request.headers.get("origin") != str(request.base_url).rstrip("/"):
                    return JSONResponse({"error": "origin_denied"}, status_code=403)
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

        @app.get("/_mmos/me", include_in_schema=False)
        def _me(user: CurrentUser = Depends(mmos.user)):
            # Bootstrap the SPA from its HttpOnly cookie; never expose the JWT to JS.
            return {"sub": user.sub, "emp": user.employee_code, "name": user.name,
                    "email": user.email, "dept": user.department, "division": user.division,
                    "band": user.band, "roles": user.roles, "permissions": user.permissions,
                    "pv": user.policy_version, "platform_admin": user.platform_admin}

        @app.post("/_mmos/logout", include_in_schema=False)
        def _logout(response: Response):
            response.delete_cookie(mmos.cookie_name, path="/", secure=True, httponly=True, samesite="none")
            return {"ok": True}

        @app.post("/_mmos/session", include_in_schema=False)
        async def _session(request: Request, response: Response):
            body = await request.json()
            token = body.get("token", "")
            try:
                claims = mmos._verify(token)
            except TokenError as exc:
                raise HTTPException(status_code=401, detail={"error": exc.reason})
            # MM OS renders embeddable services in an iframe on its OWN origin, pointing
            # that iframe straight at `/_mmos/accept#token=…`. A `lax` cookie is not sent in
            # a cross-site frame at all, so the session would be set and then ignored on the
            # very next request — indistinguishable, from the user's side, from a broken
            # login. `none` is the only SameSite a framed session can use, and browsers
            # accept it only with `Secure`, which this cookie already sets.
            response.set_cookie(
                mmos.cookie_name,
                token,
                httponly=True,
                secure=True,
                samesite="none",
                path="/",
                max_age=max(0, int(claims["exp"] - time.time())),
            )
            return {"ok": True}

        @app.get("/_mmos/health", include_in_schema=False)
        def _health():
            # Reaching MM OS is the precondition for anyone signing in at all, so a health
            # check that ignores it reports "ok" straight through an outage — which is
            # exactly what every service did on 7 Sep while nobody could get in. `ok` here
            # now means "a handoff can actually succeed".
            reachable, detail = mmos.probe_os()
            return {
                "ok": reachable,
                "authority_age_seconds": mmos.authority_age_seconds,
                "persistent_trust_cache": mmos.persistent_trust_cache,
                "slug": mmos.slug,
                "version": mmos.version,
                # Neither is a secret: the issuer is in every token and the URL is in every
                # redirect. The service key is never echoed.
                "os": {
                    "reachable": reachable,
                    "url": mmos.os_url,
                    "issuer": mmos.issuer,
                    "error": detail,
                },
            }

        app.add_middleware(BaseHTTPMiddleware, dispatch=self._dispatch)
        app.add_exception_handler(HTTPException, _flat_http_exception_handler)

        # Compose with the host lifespan. FastAPI suppresses on_event handlers when a
        # custom lifespan is present (Service Desk has one).
        host_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application):
            async with host_lifespan(application) as state:
                mmos._audit_routes(application)
                if start_background:
                    mmos.poller.start()
                    mmos.heartbeat.start()
                try:
                    yield state
                finally:
                    if start_background:
                        mmos.poller.stop()
                        mmos.heartbeat.stop()

        app.router.lifespan_context = lifespan


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


def require_permission(permission: str, *, max_authority_age_seconds: int | None = None):
    """Guard an action by explicit claims; privileged actions can require recent authority.

    Roles and platform_admin never imply permission. Object ownership and department
    scope must additionally be checked by the service against the requested record.
    """
    if not permission or (max_authority_age_seconds is not None and
                          not 0 < max_authority_age_seconds <= 900):
        raise ValueError("Use a permission and an authority age between 1 and 900 seconds")

    def _dep(user: CurrentUser = Depends(_active_user_dependency)) -> CurrentUser:
        if permission not in user.permissions:
            raise HTTPException(403, {"error": "permission_required", "need": permission})
        if max_authority_age_seconds is not None:
            age = _ACTIVE.authority_age_seconds if _ACTIVE else None
            if age is None or not 0 <= age <= max_authority_age_seconds:
                raise HTTPException(503, {"error": "authority_refresh_required"})
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
