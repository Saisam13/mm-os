"""The issuer / public_url split (docs/16-decisions.md D-2026-09-08-2).

The 8 Sep outage: MMOS_ISSUER had been set to the deployment's reachable sslip.io URL so the
Google OAuth redirect worked there, which also made every service token carry that URL as its
`iss` — and the services verify against the stable https://os.m-mines.com, so every token was
rejected. The two concerns must not share one setting.
"""
from __future__ import annotations

import importlib

from app import config as config_module


def _fresh_settings(monkeypatch, **env):
    for k in ("MMOS_ISSUER", "MMOS_PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config_module.settings.cache_clear()
    try:
        return config_module.Settings()
    finally:
        config_module.settings.cache_clear()


def test_issuer_defaults_to_stable_identity(monkeypatch):
    s = _fresh_settings(monkeypatch)
    assert s.issuer == "https://os.m-mines.com"
    # With no public_url the redirect falls back to issuer — the original single-value shape.
    assert s.redirect_uri == "https://os.m-mines.com/api/auth/google/callback"


def test_public_url_moves_the_oauth_redirect_without_touching_the_token_issuer(monkeypatch):
    """The fix: the deployment lives at an sslip.io host, but tokens still say os.m-mines.com."""
    s = _fresh_settings(
        monkeypatch,
        MMOS_PUBLIC_URL="http://hrxd6lgu3h7qpnkbpy2mqgdc.200.234.36.153.sslip.io",
    )
    # OAuth redirect follows the reachable host (matches Google Console).
    assert s.redirect_uri == (
        "http://hrxd6lgu3h7qpnkbpy2mqgdc.200.234.36.153.sslip.io/api/auth/google/callback"
    )
    # But the token issuer stays the stable identity every service verifies against.
    assert s.issuer == "https://os.m-mines.com"


def test_setting_issuer_to_the_host_is_what_broke_login(monkeypatch):
    """Guards the regression: if issuer is (mis)set to the host, that is what tokens carry."""
    s = _fresh_settings(
        monkeypatch,
        MMOS_ISSUER="http://hrxd6lgu3h7qpnkbpy2mqgdc.200.234.36.153.sslip.io",
    )
    assert s.issuer != "https://os.m-mines.com"  # exactly the misconfiguration to avoid
