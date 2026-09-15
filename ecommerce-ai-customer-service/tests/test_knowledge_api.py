"""知识库接口（/knowledge）测试。"""

from __future__ import annotations


def test_search_returns_hits_with_answer(client):
    resp = client.get("/knowledge/search", params={"q": "退款多久到账"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "退款多久到账"
    assert body["backend"] == "TfidfRetriever"
    assert body["hits"][0]["id"] == "faq_010"
    assert body["hits"][0]["answer"]  # 返回完整答案
    assert body["hits"][0]["matched"] is True


def test_search_respects_top_k(client):
    body = client.get("/knowledge/search", params={"q": "订单", "top_k": 2}).json()
    assert body["top_k"] == 2
    assert len(body["hits"]) <= 2


def test_search_default_top_k(client):
    body = client.get("/knowledge/search", params={"q": "订单"}).json()
    assert body["top_k"] == 3


def test_search_irrelevant_query_not_matched(client):
    body = client.get("/knowledge/search", params={"q": "今天天气怎么样"}).json()
    assert all(h["matched"] is False for h in body["hits"])


def test_search_requires_query(client):
    assert client.get("/knowledge/search").status_code == 422
    assert client.get("/knowledge/search", params={"q": ""}).status_code == 422


def test_search_rejects_bad_top_k(client):
    assert client.get("/knowledge/search", params={"q": "订单", "top_k": 0}).status_code == 422
    assert client.get("/knowledge/search", params={"q": "订单", "top_k": 999}).status_code == 422


def test_stats(client):
    body = client.get("/knowledge/stats").json()
    assert body["faq_count"] >= 20
    assert body["backend"] == "TfidfRetriever"
    assert body["top_k"] >= 1
    assert "min_score" in body


def test_reload_requires_admin_key(client):
    resp = client.post("/knowledge/reload", headers={"X-Admin-Key": "wrong"})
    assert resp.status_code == 401
