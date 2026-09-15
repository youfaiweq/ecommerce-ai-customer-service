"""限流中间件测试。"""

from __future__ import annotations

import pytest

from app.config import settings
from app.utils.rate_limit import RateLimitMiddleware


@pytest.fixture
def limited(monkeypatch):
    """开启限流：每窗口 2 次。"""
    monkeypatch.setattr(settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rate_limit_requests", 2, raising=False)
    monkeypatch.setattr(settings, "rate_limit_window", 60, raising=False)
    RateLimitMiddleware.reset_all()
    return settings


def test_allows_requests_within_limit(client, limited):
    assert client.get("/knowledge/stats").status_code == 200
    assert client.get("/knowledge/stats").status_code == 200


def test_blocks_request_over_limit(client, limited):
    assert client.get("/knowledge/stats").status_code == 200
    assert client.get("/knowledge/stats").status_code == 200

    resp = client.get("/knowledge/stats")
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"]["code"] == "rate_limited"
    assert "请求过于频繁" in body["error"]["message"]


def test_429_includes_retry_after_header(client, limited):
    client.get("/knowledge/stats")
    client.get("/knowledge/stats")
    resp = client.get("/knowledge/stats")
    assert resp.status_code == 429
    assert resp.headers.get("retry-after")
    assert int(resp.headers["retry-after"]) >= 1


def test_exempt_paths_are_not_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rate_limit_requests", 1, raising=False)
    RateLimitMiddleware.reset_all()
    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_disabled_limiter_allows_everything(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False, raising=False)
    monkeypatch.setattr(settings, "rate_limit_requests", 1, raising=False)
    RateLimitMiddleware.reset_all()
    for _ in range(5):
        assert client.get("/knowledge/stats").status_code == 200


def test_reset_all_clears_counters(client, limited):
    client.get("/knowledge/stats")
    client.get("/knowledge/stats")
    assert client.get("/knowledge/stats").status_code == 429

    RateLimitMiddleware.reset_all()
    assert client.get("/knowledge/stats").status_code == 200


def test_client_key_uses_connection_host_by_default(monkeypatch):
    """默认不信任 X-Forwarded-For，避免被伪造绕过限流。"""
    monkeypatch.setattr(settings, "trust_forwarded_for", False, raising=False)

    class _Req:
        headers = {"x-forwarded-for": "1.2.3.4"}

        class client:
            host = "9.9.9.9"

    assert RateLimitMiddleware.client_key(_Req()) == "9.9.9.9"


def test_client_key_honours_forwarded_for_when_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_for", True, raising=False)

    class _Req:
        headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}

        class client:
            host = "9.9.9.9"

    assert RateLimitMiddleware.client_key(_Req()) == "1.2.3.4"


def test_login_uses_stricter_dedicated_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "login_rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rate_limit_requests", 100, raising=False)
    monkeypatch.setattr(settings, "login_rate_limit_requests", 2, raising=False)
    monkeypatch.setattr(settings, "login_rate_limit_window", 60, raising=False)
    RateLimitMiddleware.reset_all()

    for _ in range(2):
        assert client.post("/auth/login", json={"user_id": "u1001", "password": "wrong"}).status_code == 401
    assert client.post("/auth/login", json={"user_id": "u1001", "password": "wrong"}).status_code == 429
