"""The MM OS bar on a service page reads GET /api/me cross-origin (app/embed_cors.py)."""
from __future__ import annotations

import pytest

from app import config as config_module
from app.embed_cors import allowed_origin


def test_allowed_origin_is_https_under_the_cookie_domain_only():
    d = ".m-mines.in"
    assert allowed_origin("https://po.m-mines.in", d)
    assert allowed_origin("https://m-mines.in", d)
    assert allowed_origin("https://a.b.m-mines.in", d)
    assert not allowed_origin("http://po.m-mines.in", d)          # not https
    assert not allowed_origin("https://evil-m-mines.in", d)       # lookalike
    assert not allowed_origin("https://m-mines.in.evil.com", d)   # suffix trick
    assert not allowed_origin("https://po.m-mines.in", "")        # no cookie domain: nothing
    assert not allowed_origin(None, d)


@pytest.fixture
def cookie_domain(monkeypatch):
    monkeypatch.setenv("MMOS_COOKIE_DOMAIN", ".m-mines.in")
    config_module.settings.cache_clear()
    yield
    config_module.settings.cache_clear()


def test_api_me_answers_service_origins_with_credentials(client, make_user, sign_in, cookie_domain):
    sign_in(make_user())
    r = client.get("/api/me", headers={"Origin": "https://po.m-mines.in"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://po.m-mines.in"
    assert r.headers["access-control-allow-credentials"] == "true"

    # signed out still gets CORS headers, so the bar can tell "not signed in" from "blocked"
    client.cookies.clear()
    r = client.get("/api/me", headers={"Origin": "https://po.m-mines.in"})
    assert r.status_code == 401
    assert r.headers["access-control-allow-origin"] == "https://po.m-mines.in"


def test_foreign_origin_and_other_paths_get_nothing(client, make_user, sign_in, cookie_domain):
    sign_in(make_user())
    r = client.get("/api/me", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    r = client.get("/api/admin/services", headers={"Origin": "https://po.m-mines.in"})
    assert "access-control-allow-origin" not in r.headers
