"""Trust-state outage, revocation, malformed-claim and browser-boundary regressions."""
import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from mmos_client import TokenError, require_permission
from test_mmos_client import keypair, stub, mint, make_mmos, _build_app


def test_restart_during_outage_uses_fresh_persisted_trust(keypair, stub, tmp_path):
    pem, _, _ = keypair
    token = mint(pem)
    first = make_mmos(stub, state_directory=str(tmp_path))
    assert first._verify(token)["sub"] == "user:1"
    stub.unreachable = True
    restarted = make_mmos(stub, state_directory=str(tmp_path))
    assert restarted._verify(token)["sub"] == "user:1"
    saved = "".join(p.read_text() for p in tmp_path.glob("*.json"))
    assert token not in saved and "mmk_test" not in saved


def test_restart_preserves_subject_revocation(keypair, stub, tmp_path):
    pem, _, _ = keypair
    token = mint(pem)
    first = make_mmos(stub, state_directory=str(tmp_path))
    first._verify(token)
    stub.revoked_subs = [{"sub": "user:1"}]
    assert first.poller.poll_once()
    stub.unreachable = True
    restarted = make_mmos(stub, state_directory=str(tmp_path))
    with pytest.raises(TokenError, match="revoked"):
        restarted._verify(token)


def test_cold_outage_does_not_establish_trust(keypair, stub):
    pem, _, _ = keypair
    stub.unreachable = True
    with pytest.raises(TokenError):
        make_mmos(stub)._verify(mint(pem))


def test_stale_revocations_block_still_valid_token(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    token = mint(pem)
    mmos._verify(token)
    mmos._denylist.last_success_at -= 901
    stub.unreachable = True
    with pytest.raises(TokenError, match="authority_unavailable"):
        mmos._verify(token)


def test_known_key_trust_expires(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    token = mint(pem)
    mmos._verify(token)
    mmos._jwks._last_success -= 86401
    stub.unreachable = True
    with pytest.raises(TokenError, match="unknown_kid"):
        mmos._verify(token)


@pytest.mark.parametrize("extra", [{"iat": None}, {"exp": "tomorrow"}, {"exp": float("nan")}, {"iat": True}])
def test_invalid_time_claims_fail_closed(keypair, stub, extra):
    pem, _, _ = keypair
    with pytest.raises(TokenError, match="invalid_time_claims"):
        make_mmos(stub)._verify(mint(pem, extra=extra))


@pytest.mark.parametrize("extra", [{"permissions": "service.admin"}, {"roles": "admin"}])
def test_invalid_authority_types_fail_closed(keypair, stub, extra):
    pem, _, _ = keypair
    with pytest.raises(TokenError, match="invalid_authority_claims"):
        make_mmos(stub)._verify(mint(pem, extra=extra))


def test_future_nbf_is_enforced(keypair, stub):
    pem, _, _ = keypair
    with pytest.raises(TokenError, match="not_yet_valid"):
        make_mmos(stub)._verify(mint(pem, extra={"nbf": int(time.time()) + 120}))


def test_handoff_uses_cookie_metadata_and_rejects_foreign_origin(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    with TestClient(_build_app(mmos), base_url="https://testserver", headers={"Origin": "https://testserver"}) as client:
        token = mint(pem, extra={"permissions": ["view"], "pv": "test-policy"})
        assert client.post("/_mmos/session", json={"token": token}).status_code == 200
        me = client.get("/_mmos/me")
        assert me.status_code == 200 and me.json()["permissions"] == ["view"]
        assert token not in me.text
        assert client.post("/_mmos/logout", headers={"Origin": "https://foreign.invalid"}).status_code == 403
        assert client.post("/_mmos/logout").status_code == 200
        assert client.get("/_mmos/me").status_code == 401
        page = client.get("/_mmos/accept").text
        assert "localStorage" not in page and 'searchParams.set("mmos_token"' not in page


def test_explicit_permission_and_recent_authority_guard(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    app = FastAPI()

    @app.post("/approve")
    def approve(user=Depends(require_permission("ticket.approve", max_authority_age_seconds=300))):
        return {"sub": user.sub}

    mmos.install(app, start_background=False)
    with TestClient(app) as client:
        role_only = mint(pem, extra={"roles": ["admin"], "platform_admin": True, "permissions": []})
        assert client.post("/approve", headers={"Authorization": f"Bearer {role_only}"}).status_code == 403
        allowed = mint(pem, extra={"permissions": ["ticket.approve"]})
        headers = {"Authorization": f"Bearer {allowed}"}
        assert client.post("/approve", headers=headers).status_code == 200
        mmos._denylist.last_success_at -= 301
        assert client.post("/approve", headers=headers).status_code == 503


def test_background_workers_stop_and_restart(stub):
    mmos = make_mmos(stub)
    for worker in [mmos.poller, mmos.heartbeat]:
        worker.start()
        first = worker._thread
        worker.stop()
        assert not first.is_alive()
        worker.start()
        assert worker._thread is not first and worker._thread.is_alive()
        worker.stop()
        assert not worker._thread.is_alive()
