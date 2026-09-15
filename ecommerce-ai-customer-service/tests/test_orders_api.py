"""订单接口（/orders）测试。

鉴权：所有 /orders 端点都需要登录；本测试通过 ``auth_headers`` 夹具提供 u1001 的 token。
"""

from __future__ import annotations


def test_get_order_exact(client, auth_headers):
    resp = client.get("/orders/202609030002", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["matched_by"] == "exact"
    assert body["order"]["order_no"] == "202609030002"


def test_get_order_by_suffix(client, auth_headers):
    resp = client.get("/orders/0002", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched_by"] == "suffix"
    assert body["order"]["order_no"] == "202609030002"


def test_get_order_by_contains(client, make_token):
    """contains 匹配：订单 202612345678 归属 u1004，需用 u1004 的 token。"""
    headers = {"Authorization": f"Bearer {make_token('u1004')}"}
    body = client.get("/orders/123456", headers=headers).json()
    assert body["matched_by"] == "contains"
    assert body["order_no"] == "202612345678"


def test_get_order_not_found(client, auth_headers):
    resp = client.get("/orders/999999999999", headers=auth_headers)
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "order_not_found"
    assert "可用订单号" not in body["error"]["message"]


def test_list_orders_for_current_user(client, auth_headers):
    """登录用户 u1001 查询自己的全部订单（不再传 user_id query）。"""
    resp = client.get("/orders", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "u1001"
    assert body["count"] == 3
    assert all(o["user_id"] == "u1001" for o in body["orders"])


def test_list_orders_for_other_user(client, auth_headers_u1002):
    """u1002 登录后查 /orders 只应返回 u1002 自己的订单。"""
    body = client.get("/orders", headers=auth_headers_u1002).json()
    assert body["user_id"] == "u1002"
    assert all(o["user_id"] == "u1002" for o in body["orders"])


# ---------------------------------------------------------------------------
# 鉴权新增用例
# ---------------------------------------------------------------------------
def test_list_orders_unauthorized(client):
    """不带 token 调用 /orders → 401。"""
    resp = client.get("/orders")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized"


def test_get_order_unauthorized(client):
    """不带 token 调用 /orders/{order_no} → 401。"""
    resp = client.get("/orders/202609030002")
    assert resp.status_code == 401


def test_get_order_forbidden_cross_user(client, auth_headers_u1002):
    """u1002 的 token 查 u1001 的订单 → 403（不暴露订单是否存在）。"""
    resp = client.get("/orders/202609030002", headers=auth_headers_u1002)
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "order_forbidden"


def test_get_order_with_invalid_token(client):
    """伪造的 token → 401。"""
    resp = client.get(
        "/orders/202609030002",
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert resp.status_code == 401
