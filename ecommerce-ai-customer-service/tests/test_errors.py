"""统一错误处理测试。"""

from __future__ import annotations


def test_404_has_unified_error_shape(client):
    resp = client.get("/definitely-not-a-route")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "http_404"


def test_method_not_allowed_has_unified_shape(client):
    resp = client.get("/chat")
    assert resp.status_code == 405
    assert resp.json()["error"]["code"] == "http_405"


def test_validation_error_shape_and_detail(client):
    resp = client.post("/chat", json={"message": ""})
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "请求参数校验失败"
    assert isinstance(error["detail"], list) and error["detail"]
    first = error["detail"][0]
    assert set(first) == {"loc", "msg", "type"}


def test_validation_detail_is_json_serialisable(client):
    """校验明细必须可 JSON 序列化（pydantic 原始 ctx 可能含异常对象）。"""
    resp = client.get("/knowledge/search", params={"q": "订单", "top_k": "abc"})
    assert resp.status_code == 422
    assert resp.json()["error"]["detail"]


def test_order_not_found_does_not_leak_order_numbers(client, auth_headers):
    """未找到订单时保留结构化错误，但不泄露其他订单号。"""
    resp = client.get("/orders/999999999999", headers=auth_headers)
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "order_not_found"
    assert "可用订单号" not in body["error"]["message"]


def test_unhandled_exception_returns_500(prod_client):
    """生产模式（debug=False）下，未捕获异常应返回统一 500 JSON，且不泄露堆栈。"""
    from app.main import app

    @app.get("/__boom__")
    async def _boom():  # pragma: no cover - 仅用于触发异常
        raise RuntimeError("sensitive internal detail")

    try:
        resp = prod_client.get("/__boom__")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "internal_error"
        assert body["error"]["message"] == "服务器内部错误，请稍后重试"
        assert "sensitive internal detail" not in resp.text
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/__boom__"
        ]
