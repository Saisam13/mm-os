"""FROZEN CONTRACT — do not edit in a build agent. See docs/09-build-agents.md.

Network posture enforcement plus request ids. This is the second of the two independent
enforcement points described in docs/06-network-security.md; the VPS firewall is the first.
"""
from __future__ import annotations

import uuid
from ipaddress import ip_address

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .deps import client_ip

# Paths that must answer even from outside the allowlist, so that health checks and
# token verification never depend on network posture.
ALWAYS_OPEN = ("/healthz", "/.well-known/jwks.json")


class NetworkGate(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cfg = settings()
        if cfg.network_mode == "private" and not request.url.path.startswith(ALWAYS_OPEN):
            try:
                ip = ip_address(client_ip(request))
                if not any(ip in net for net in cfg.cidrs):
                    return JSONResponse(
                        {"error": "network_denied",
                         "message": "MM OS is reachable from the office network or VPN only."},
                        status_code=403,
                    )
            except ValueError:
                return JSONResponse({"error": "network_denied"}, status_code=403)
        return await call_next(request)


class RequestId(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


# docs/06 asks for `default-src 'self'; connect-src 'self'; frame-ancestors 'none'`. Applied as
# written, with two exceptions the doc did not anticipate, both required by decisions made
# elsewhere and neither widening script execution:
#
#   * Roboto and Roboto Condensed are the brand faces (brand/BRAND.md) and are loaded from
#     Google Fonts, so the stylesheet host and the font host must be reachable. Self-hosting
#     the two families would let this return to a literal `default-src 'self'` and remove an
#     outbound dependency that a network-restricted deployment may not even have.
#   * The shell uses ~26 inline `style` attributes for values computed at render time (service
#     mark colours, sparkline geometry), so style attributes must be allowed. This does not
#     permit inline <script>; script-src stays `'self'`.
CSP = "; ".join([
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "script-src 'self'",
    "connect-src 'self'",
    "img-src 'self' data:",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
])


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        # embed.js is cross-origin by design; the shell itself is never framed.
        if not request.url.path.startswith("/embed.js"):
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response
