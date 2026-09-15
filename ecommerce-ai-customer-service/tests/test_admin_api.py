"""管理接口（/admin）测试。"""

from __future__ import annotations

from app.config import settings
from app.services.log_store import log_store


def _seed() -> None:
    """写入两条会话的日志作为测试数据。"""
    log_store.record_message("adm-1", "user", "查订单", {"intent": "query_order"})
    log_store.record_message("adm-1", "assistant", "订单详情…", {"grounded": True})
    log_store.record_message("adm-2", "user", "转人工", {"intent": "transfer_human"})
    log_store.record_message("adm-2", "assistant", "已转接", {"transferred": True})


def test_list_sessions(client):
    _seed()
    resp = client.get("/admin/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["count"] == 2
    assert {s["session_id"] for s in body["sessions"]} == {"adm-1", "adm-2"}


def test_list_sessions_pagination(client):
    _seed()
    body = client.get("/admin/sessions", params={"limit": 1, "offset": 0}).json()
    assert body["count"] == 1
    assert body["total"] == 2


def test_list_sessions_rejects_bad_limit(client):
    assert client.get("/admin/sessions", params={"limit": 0}).status_code == 422
    assert client.get("/admin/sessions", params={"limit": 999}).status_code == 422


def test_admin_stats(client):
    _seed()
    stats = client.get("/admin/stats").json()
    assert stats["total_sessions"] == 2
    assert stats["total_messages"] == 4
    assert stats["transferred_sessions"] == 1
    assert stats["intent_distribution"]["query_order"] == 1


def test_session_detail(client):
    _seed()
    resp = client.get("/admin/sessions/adm-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["message_count"] == 2
    assert body["session"]["session_id"] == "adm-1"
    assert body["messages"][0]["role"] == "user"


def test_session_detail_404(client):
    resp = client.get("/admin/sessions/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "http_404"


def test_admin_search(client):
    _seed()
    # "订单" 同时命中用户消息与助手回复 → 2 条，且都属于 adm-1
    body = client.get("/admin/search", params={"q": "订单"}).json()
    assert body["count"] == 2
    assert {m["session_id"] for m in body["messages"]} == {"adm-1"}

    # 更精确的关键词 → 1 条
    single = client.get("/admin/search", params={"q": "转人工"}).json()
    assert single["count"] == 1
    assert single["messages"][0]["session_id"] == "adm-2"

    empty = client.get("/admin/search", params={"q": "找不到的词xyz"}).json()
    assert empty["count"] == 0


def test_admin_search_requires_query(client):
    assert client.get("/admin/search").status_code == 422


def test_delete_session_log(client):
    _seed()
    resp = client.delete("/admin/sessions/adm-1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    assert client.get("/admin/sessions/adm-1").status_code == 404


def test_delete_unknown_session_404(client):
    assert client.delete("/admin/sessions/nope").status_code == 404


# ----------------------------------------------------------------------
# 鉴权
# ----------------------------------------------------------------------
def test_admin_rejects_when_no_key_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "", raising=False)
    resp = client.get("/admin/stats")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "admin_key_not_configured"


def test_admin_requires_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "s3cret", raising=False)
    assert client.get("/admin/stats").status_code == 401


def test_admin_rejects_wrong_key(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "s3cret", raising=False)
    resp = client.get("/admin/stats", headers={"X-Admin-Key": "wrong"})
    assert resp.status_code == 401
    assert "X-Admin-Key" in resp.json()["error"]["message"]


def test_admin_accepts_correct_key(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "s3cret", raising=False)
    resp = client.get("/admin/stats", headers={"X-Admin-Key": "s3cret"})
    assert resp.status_code == 200
