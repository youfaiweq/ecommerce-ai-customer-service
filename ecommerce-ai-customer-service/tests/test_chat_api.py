"""/chat 接口端到端测试（大模型使用假客户端）。"""

from __future__ import annotations


def _system_prompt(fake) -> str:
    """取出最后一次调用中发给模型的 system prompt。"""
    return fake.calls[-1]["messages"][0]["content"]


def test_chat_basic_reply(client, fake_llm):
    fake_llm.reply = "您好，很高兴为您服务。"
    resp = client.post("/chat", json={"message": "你好"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "您好，很高兴为您服务。"
    assert data["session_id"]
    assert data["intent"]["intent"] == "other"


def test_chat_returns_new_session_id_when_absent(client, fake_llm):
    data = client.post("/chat", json={"message": "你好"}).json()
    assert len(data["session_id"]) == 32


def test_chat_reuses_given_session_id(client, fake_llm):
    data = client.post("/chat", json={"message": "你好", "session_id": "my-session"}).json()
    assert data["session_id"] == "my-session"


def test_chat_order_lookup_injects_data_into_prompt(client, fake_llm, make_token):
    resp = client.post(
        "/chat",
        json={"message": "查一下我的订单 123456"},
        headers={"Authorization": f"Bearer {make_token('u1004')}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"]["intent"] == "query_order"
    assert data["order_no"] == "202612345678"
    assert data["order_found"] is True

    system = _system_prompt(fake_llm)
    assert "订单号：202612345678" in system
    assert "物流公司" in system


def test_chat_slot_reuse_across_turns(client, fake_llm, make_token):
    headers = {"Authorization": f"Bearer {make_token('u1004')}"}
    first = client.post("/chat", json={"message": "查一下我的订单 123456"}, headers=headers).json()
    sid = first["session_id"]

    second = client.post(
        "/chat", json={"message": "那物流到哪了", "session_id": sid}, headers=headers
    ).json()
    assert second["intent"]["intent"] == "query_logistics"
    assert second["order_no"] == "202612345678"
    assert second["order_found"] is True
    assert "订单号：202612345678" in _system_prompt(fake_llm)


def test_chat_asks_for_order_number_when_missing(client, fake_llm):
    data = client.post("/chat", json={"message": "我的订单怎么还没发货"}).json()
    assert data["order_found"] is False
    assert data["order_no"] is None
    assert "【本轮提示】" in _system_prompt(fake_llm)


def test_chat_order_not_found(client, fake_llm):
    data = client.post("/chat", json={"message": "查订单 999999999999"}).json()
    assert data["order_found"] is False
    assert data["order_no"] == "999999999999"
    assert "未找到订单号" in _system_prompt(fake_llm)


def test_chat_does_not_disclose_another_users_order(client, fake_llm, auth_headers_u1002):
    resp = client.post(
        "/chat",
        json={"message": "查询订单 202609030002"},
        headers=auth_headers_u1002,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["order_found"] is False
    system = _system_prompt(fake_llm)
    assert "订单号：202609030002" not in system
    assert "为保护隐私" in system


def test_chat_does_not_disclose_orders_to_anonymous_user(client, fake_llm):
    resp = client.post("/chat", json={"message": "查询订单 202609030002"})
    assert resp.status_code == 200
    assert resp.json()["order_found"] is False
    assert "订单号：202609030002" not in _system_prompt(fake_llm)


def test_chat_grounded_by_knowledge_base(client, fake_llm):
    data = client.post("/chat", json={"message": "退款多久能到账？"}).json()
    assert data["grounded"] is True
    assert data["sources"]
    assert data["sources"][0]["id"] == "faq_010"


def test_chat_transfer_human_skips_llm(client, fake_llm):
    data = client.post("/chat", json={"message": "我要转人工"}).json()
    assert data["transferred"] is True
    assert data["intent"]["intent"] == "transfer_human"
    assert "人工客服" in data["reply"]
    assert fake_llm.calls == []  # 未调用大模型


def test_chat_uncertain_reply_triggers_transfer_hint(client, fake_llm_factory):
    fake = fake_llm_factory(reply="抱歉，我无法回答这个问题。", intent="other")
    data = client.post("/chat", json={"message": "随便聊聊"}).json()
    assert data["transferred"] is True
    assert "人工客服" in data["reply"]
    assert len(fake.calls) == 2  # 意图兜底分类 + 生成


def test_chat_order_flow_not_marked_transferred(client, fake_llm_factory):
    """订单流程中即使模型措辞不确定，也不应误判为转人工。"""
    fake_llm_factory(reply="抱歉，我无法回答这个问题。", intent="other")
    data = client.post("/chat", json={"message": "订单 0002 帮我看看"}).json()
    assert data["intent"]["intent"] == "query_order"
    assert data["transferred"] is False


def test_chat_empty_message_returns_422_with_error_shape(client, fake_llm):
    resp = client.post("/chat", json={"message": ""})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["detail"]  # 含字段级明细


def test_chat_missing_field_returns_422(client):
    assert client.post("/chat", json={}).status_code == 422


def test_chat_history_and_clear(client, fake_llm, auth_headers):
    sid = client.post("/chat", json={"message": "你好"}, headers=auth_headers).json()["session_id"]

    history = client.get(f"/chat/{sid}", headers=auth_headers)
    assert history.status_code == 200
    assert len(history.json()["messages"]) == 2

    cleared = client.delete(f"/chat/{sid}", headers=auth_headers)
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True
    assert client.get(f"/chat/{sid}", headers=auth_headers).json()["messages"] == []


def test_chat_history_unknown_session_404(client):
    resp = client.get("/chat/not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "http_404"


def test_chat_clear_unknown_session_404(client):
    resp = client.delete("/chat/not-exist")
    assert resp.status_code == 404


def test_chat_turn_is_persisted_to_log_store(client, fake_llm):
    """/chat 之后，会话应可在管理接口中查到。"""
    sid = client.post("/chat", json={"message": "退款多久能到账？"}).json()["session_id"]

    sessions = client.get("/admin/sessions").json()
    assert any(s["session_id"] == sid for s in sessions["sessions"])

    detail = client.get(f"/admin/sessions/{sid}").json()
    assert detail["message_count"] == 2
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][0]["intent"] == "return_exchange"
    assert detail["session"]["last_intent"] == "return_exchange"


def test_health_and_root(client):
    assert client.get("/").json() == "Hello, AI Customer Service"
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["app"]


# ---------------------------------------------------------------------------
# 鉴权：meta 中 user_id 字段（登录/匿名）
# ---------------------------------------------------------------------------
def test_chat_anonymous_meta_has_null_user_id(client, fake_llm):
    """匿名对话：响应里 user_id 为 null。"""
    data = client.post("/chat", json={"message": "你好"}).json()
    assert "user_id" in data
    assert data["user_id"] is None


def test_chat_authenticated_meta_has_user_id(client, fake_llm, auth_headers):
    """登录对话：响应里 user_id 为当前登录用户。"""
    data = client.post(
        "/chat",
        json={"message": "你好"},
        headers=auth_headers,
    ).json()
    assert data["user_id"] == "u1001"


def test_chat_session_binds_user_id_to_slot(client, fake_llm, auth_headers):
    """登录后，user_id 被写入会话槽位，GET /chat/{sid} 也能取到。"""
    sid = client.post(
        "/chat",
        json={"message": "你好"},
        headers=auth_headers,
    ).json()["session_id"]
    history = client.get(f"/chat/{sid}", headers=auth_headers).json()
    assert history["user_id"] == "u1001"


def test_chat_session_rejects_other_authenticated_user(
    client, fake_llm, auth_headers, auth_headers_u1002
):
    sid = client.post("/chat", json={"message": "你好"}, headers=auth_headers).json()["session_id"]
    assert client.get(f"/chat/{sid}", headers=auth_headers_u1002).status_code == 403
    assert client.delete(f"/chat/{sid}", headers=auth_headers_u1002).status_code == 403
    assert client.post(
        "/chat", json={"message": "继续", "session_id": sid}, headers=auth_headers_u1002
    ).status_code == 403


def test_chat_history_anonymous_has_null_user_id(client, fake_llm):
    """匿名对话历史：user_id 字段为 null。"""
    created = client.post("/chat", json={"message": "你好"}).json()
    sid = created["session_id"]
    history = client.get(f"/chat/{sid}", params={"session_token": created["session_token"]}).json()
    assert history["user_id"] is None


def test_anonymous_session_requires_its_random_token(client, fake_llm):
    created = client.post("/chat", json={"message": "你好"}).json()
    sid = created["session_id"]
    token = created["session_token"]
    assert token
    assert client.get(f"/chat/{sid}").status_code == 403
    assert client.get(f"/chat/{sid}", params={"session_token": "wrong-token-value-1234"}).status_code == 403
    history = client.get(f"/chat/{sid}", params={"session_token": token})
    assert history.status_code == 200
    assert history.json()["session_token"] == token


def test_anonymous_session_continue_requires_and_accepts_its_token(client, fake_llm):
    """匿名会话继续发送消息时，错误凭证拒绝，正确凭证允许。"""
    created = client.post("/chat", json={"message": "你好"}).json()
    sid = created["session_id"]
    token = created["session_token"]

    denied = client.post(
        "/chat",
        json={"message": "继续问一个问题", "session_id": sid, "session_token": "wrong-token-value-1234"},
    )
    assert denied.status_code == 403

    accepted = client.post(
        "/chat",
        json={"message": "继续问一个问题", "session_id": sid, "session_token": token},
    )
    assert accepted.status_code == 200
    assert accepted.json()["session_id"] == sid


def test_feedback_cannot_be_written_to_another_anonymous_session(client, fake_llm):
    """匿名反馈同样受 session token 保护，不能借 session_id 越权写入。"""
    first = client.post("/chat", json={"message": "你好"}).json()
    second = client.post("/chat", json={"message": "你好"}).json()

    denied = client.post(f"/chat/{first['session_id']}/feedback", json={"score": 1})
    assert denied.status_code == 403

    accepted = client.post(
        f"/chat/{first['session_id']}/feedback",
        params={"session_token": first["session_token"]},
        json={"score": 1},
    )
    assert accepted.status_code == 200

    from app.services.log_store import log_store

    assert len(log_store.get_feedback_for_session(first["session_id"])) == 1
    assert log_store.get_feedback_for_session(second["session_id"]) == []
