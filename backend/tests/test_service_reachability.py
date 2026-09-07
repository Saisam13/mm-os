"""The guardrail for the 7 Sep outage.

Every launch URL MM OS mints is `{base_url}/_mmos/accept#token=…`. When the m-mines.com
subdomains stopped resolving to the VPS, the registry still held well-formed https URLs and
the services themselves were healthy on their own hostnames — the only symptom was users
bouncing back to the MM OS home page with no error anywhere. These tests pin the behaviour
of the route that makes that visible before a person has to discover it by failing to log in.
"""
from __future__ import annotations

import httpx
import pytest

from app.routers import platform


@pytest.fixture()
def fake_web(monkeypatch):
    """Swaps the probe's HTTP client for a routing table keyed on the URL it fetches."""
    routes: dict[str, httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        resp = routes.get(str(request.url))
        if resp is None:
            raise httpx.ConnectError("Name or service not known", request=request)
        return resp

    real = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(platform.httpx, "AsyncClient", factory)
    return routes


def _health(slug: str, *, os_reachable: bool = True, error: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "ok": os_reachable,
            "slug": slug,
            "version": "1.0.0",
            "os": {
                "reachable": os_reachable,
                "url": "https://os.m-mines.com",
                "issuer": "https://os.m-mines.com",
                "error": error,
            },
        },
    )


def _admin(make_employee, make_user, sign_in, code: str):
    user = make_user(employee=make_employee(employee_code=code), is_platform_admin=True)
    sign_in(user)
    return user


def test_healthy_service_reads_as_reachable(
    client, make_employee, make_user, make_service, sign_in, fake_web
):
    _admin(make_employee, make_user, sign_in, "MMREACH1")
    make_service(slug="reach-ok", base_url="https://reach-ok.example")
    fake_web["https://reach-ok.example/_mmos/health"] = _health("reach-ok")

    body = client.get("/api/admin/services/reachability").json()
    row = next(s for s in body["services"] if s["slug"] == "reach-ok")
    assert row["reachable"] is True
    assert row["detail"] is None
    assert row["issuer"] == "https://os.m-mines.com"


def test_dead_hostname_is_reported_not_silently_tolerated(
    client, make_employee, make_user, make_service, sign_in, fake_web
):
    """The outage itself: DNS moved, nothing answers, the registry never noticed."""
    _admin(make_employee, make_user, sign_in, "MMREACH2")
    make_service(slug="reach-dead", base_url="https://gone.example")

    body = client.get("/api/admin/services/reachability").json()
    row = next(s for s in body["services"] if s["slug"] == "reach-dead")
    assert row["reachable"] is False
    assert "ConnectError" in row["detail"]
    assert body["unreachable"] >= 1


def test_parked_host_answering_200_html_is_not_healthy(
    client, make_employee, make_user, make_service, sign_in, fake_web
):
    """A shared-hosting landing page returns a cheerful 200. It is still a broken pointer."""
    _admin(make_employee, make_user, sign_in, "MMREACH3")
    make_service(slug="reach-parked", base_url="https://parked.example")
    fake_web["https://parked.example/_mmos/health"] = httpx.Response(
        200, text="<!DOCTYPE html><h1>403</h1>", headers={"content-type": "text/html"}
    )

    row = next(
        s for s in client.get("/api/admin/services/reachability").json()["services"]
        if s["slug"] == "reach-parked"
    )
    assert row["reachable"] is False
    assert "not an MM OS service here" in row["detail"]


def test_crossed_registry_rows_are_caught(
    client, make_employee, make_user, make_service, sign_in, fake_web
):
    """Two services pointed at each other's URL both answer 200. Only the slug gives it away."""
    _admin(make_employee, make_user, sign_in, "MMREACH4")
    make_service(slug="reach-a", base_url="https://b.example")
    fake_web["https://b.example/_mmos/health"] = _health("reach-b")

    row = next(
        s for s in client.get("/api/admin/services/reachability").json()["services"]
        if s["slug"] == "reach-a"
    )
    assert row["reachable"] is False
    assert "is the 'reach-b' service" in row["detail"]


def test_service_that_cannot_reach_mm_os_is_a_distinct_failure(
    client, make_employee, make_user, make_service, sign_in, fake_web
):
    """The other half of the outage: the service is up, but its own pointer at MM OS is
    wrong, so every handoff token fails and nobody can get in."""
    _admin(make_employee, make_user, sign_in, "MMREACH5")
    make_service(slug="reach-lost", base_url="https://lost.example")
    fake_web["https://lost.example/_mmos/health"] = _health(
        "reach-lost", os_reachable=False, error="expected JSON, got text/html"
    )

    row = next(
        s for s in client.get("/api/admin/services/reachability").json()["services"]
        if s["slug"] == "reach-lost"
    )
    assert row["reachable"] is False
    assert "cannot reach MM OS" in row["detail"]


def test_external_services_are_only_checked_for_liveness(
    client, make_employee, make_user, make_service, sign_in, fake_web
):
    """ERPNext and Twenty run their own sessions and expose no `/_mmos/health`."""
    _admin(make_employee, make_user, sign_in, "MMREACH6")
    make_service(slug="reach-ext", base_url="https://erp.example", launch_mode="external")
    fake_web["https://erp.example/"] = httpx.Response(200, text="<html>login</html>")

    row = next(
        s for s in client.get("/api/admin/services/reachability").json()["services"]
        if s["slug"] == "reach-ext"
    )
    assert row["reachable"] is True


def test_probe_requires_admin(client, make_employee, make_user, sign_in):
    sign_in(make_user(employee=make_employee(employee_code="MMREACH7")))
    assert client.get("/api/admin/services/reachability").status_code == 403
