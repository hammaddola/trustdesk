"""API security behaviour that does not need a database (tenant resolution is stubbed)."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from trustdesk_ai.tenancy import public
from trustdesk_ai.tenancy.public import PublicTenant

KEY = "td_pk_testtenantkey123"
TENANT = PublicTenant(
    tenant_id=UUID("00000000-0000-0000-0000-00000000000a"),
    organization="Acme Studio (demo)",
    allowed_origins=frozenset({"https://www.acme.example"}),
    greeting="Hi",
    default_language="en",
    enabled_languages=("en",),
    widget_theme={},
    handoff_channels={"email": {"enabled": True, "to": "team@acme.example"}, "whatsapp": {"enabled": False}},
    setup_complete=True,
)


@pytest.fixture
def client(monkeypatch):
    async def fake_resolve(key: str):
        return TENANT if key == KEY else None

    monkeypatch.setattr(public, "resolve", fake_resolve)
    from trustdesk_ai.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


def test_admin_routes_require_auth(client):
    for method, path in [
        ("get", "/v1/admin/overview"),
        ("get", "/v1/admin/leads"),
        ("get", "/v1/admin/leads.csv"),
        ("post", "/v1/admin/playground"),
        ("patch", "/v1/admin/settings"),
        ("get", "/v1/admin/conversations"),
    ]:
        r = getattr(client, method)(path)
        assert r.status_code == 401, path
        assert r.json()["error"] == "authentication required"


def test_malformed_bearer_rejected(client):
    r = client.get("/v1/admin/overview", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401
    r = client.get("/v1/admin/overview", headers={"Authorization": "Bearer " + "x" * 500})
    assert r.status_code == 401


def test_widget_config_allowed_origin_gets_cors_and_hides_secrets(client):
    r = client.get(f"/v1/public/{KEY}/config", headers={"Origin": "https://www.acme.example"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://www.acme.example"
    body = r.json()
    assert body["handoff"] == {"email": {"enabled": True}}  # team email address never exposed
    assert "team@acme.example" not in r.text


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "https://www.acme.example.evil.com",
        "null",
        "http://www.acme.example",
        "https://www.acme.example:8443",
    ],
)
def test_disallowed_origins_blocked(client, origin):
    r = client.get(f"/v1/public/{KEY}/config", headers={"Origin": origin})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_preflight(client):
    ok = client.options(
        f"/v1/public/{KEY}/chat/stream",
        headers={"Origin": "https://www.acme.example", "Access-Control-Request-Method": "POST"},
    )
    assert ok.status_code == 204 and ok.headers["access-control-allow-origin"] == "https://www.acme.example"
    bad = client.options(
        f"/v1/public/{KEY}/chat/stream",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert bad.status_code == 403


def test_unknown_tenant_key(client):
    assert client.get("/v1/public/td_pk_doesnotexist0/config").status_code == 404


def test_security_headers_and_request_id(client):
    r = client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert len(r.headers["x-request-id"]) >= 8
    r = client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["x-request-id"] != "bad id with spaces"


def test_request_size_limit(client):
    r = client.post(
        f"/v1/public/{KEY}/chat/stream",
        content=b"x" * 70_000,
        headers={"Origin": "https://www.acme.example", "Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_validation_errors_do_not_echo_input(client):
    secret = "<script>alert('xss')</script>"
    r = client.post(
        f"/v1/public/{KEY}/leads",
        headers={"Origin": "https://www.acme.example"},
        json={"channel": "email", "visitor_id": "not-a-uuid", "idempotency_key": secret},
    )
    assert r.status_code == 422
    assert secret not in r.text and "alert" not in r.text


def test_chunked_body_over_limit_rejected_without_content_length(client):
    def chunks():
        for _ in range(20):
            yield b"x" * 8192  # 160 KB total, sent chunked (no Content-Length header)

    r = client.post(
        f"/v1/public/{KEY}/chat/stream",
        content=chunks(),
        headers={"Origin": "https://www.acme.example", "Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_failed_logins_throttle_per_email_and_ip_without_locking_out_others(client, monkeypatch):
    from trustdesk_ai.api import admin_auth
    from trustdesk_ai.auth import service as auth

    counts: dict[str, int] = {}

    class FakeLimiter:
        async def count(self, key, window):
            return counts.get(key, 0)

        async def hit(self, key, limit, window):
            counts[key] = counts.get(key, 0) + 1
            return counts[key] <= limit

    async def always_wrong(*args, **kwargs):
        raise auth.AuthError("invalid")

    monkeypatch.setattr(admin_auth, "_limiter", FakeLimiter())
    monkeypatch.setattr(auth, "login", always_wrong)
    body = {"email": "owner@example.com", "password": "wrong-password"}
    attacker = {"X-Forwarded-For": "203.0.113.9"}
    codes = [client.post("/v1/admin/auth/login", json=body, headers=attacker).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429  # attacker's source is throttled
    # Same email from a different client address is NOT locked out (keys are per email+IP, failures only).
    monkeypatch.setattr(admin_auth, "client_ip", lambda request: "198.51.100.7")
    assert client.post("/v1/admin/auth/login", json=body).status_code == 401
