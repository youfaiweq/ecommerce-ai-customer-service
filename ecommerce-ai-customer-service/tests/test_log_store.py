"""会话日志存储（SQLite）测试。"""

from __future__ import annotations

from app.config import settings
from app.services.log_store import log_store


def test_db_initialized():
    assert log_store.enabled is True
    assert log_store._ready is True
    assert log_store.db_path.name == "test_logs.db"


def test_record_message_creates_session_and_message():
    log_store.record_message("s1", "user", "你好", {"intent": "query_order"})
    log_store.record_message("s1", "assistant", "您好", {"intent": "query_order", "grounded": True})

    session = log_store.get_session("s1")
    assert session is not None
    assert session["message_count"] == 2
    assert session["last_intent"] == "query_order"

    messages = log_store.get_messages("s1")
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "你好"
    assert messages[0]["intent"] == "query_order"
    assert messages[1]["grounded"] is True


def test_sources_roundtrip_as_json():
    sources = [{"id": "faq_010", "category": "退换货", "question": "退款多久到账？", "score": 0.6962}]
    log_store.record_message("s2", "assistant", "回复", {"sources": sources})
    messages = log_store.get_messages("s2")
    assert messages[0]["sources"] == sources


def test_order_fields_persisted_and_cast_to_bool():
    log_store.record_message(
        "s3", "assistant", "订单信息", {"order_no": "202609030002", "order_found": True}
    )
    message = log_store.get_messages("s3")[0]
    assert message["order_no"] == "202609030002"
    assert message["order_found"] is True


def test_transferred_counted_in_session():
    log_store.record_message("s4", "user", "转人工", {"intent": "transfer_human"})
    log_store.record_message("s4", "assistant", "已转接", {"transferred": True})
    session = log_store.get_session("s4")
    assert session["transferred_count"] == 1


def test_list_sessions_ordered_by_recent():
    log_store.record_message("s-a", "user", "a")
    log_store.record_message("s-b", "user", "b")
    log_store.record_message("s-a", "assistant", "a2")  # s-a 变为最近活跃
    sessions = log_store.list_sessions(limit=10)
    assert sessions[0]["session_id"] == "s-a"


def test_stats_counts_and_intent_distribution():
    log_store.record_message("sx", "user", "查订单", {"intent": "query_order"})
    log_store.record_message("sy", "user", "查订单", {"intent": "query_order"})
    log_store.record_message("sz", "user", "退款", {"intent": "return_exchange"})

    stats = log_store.stats()
    assert stats["total_sessions"] == 3
    assert stats["total_messages"] == 3
    assert stats["intent_distribution"]["query_order"] == 2
    assert stats["intent_distribution"]["return_exchange"] == 1


def test_search_messages():
    log_store.record_message("sq", "user", "我的快递怎么还没到")
    results = log_store.search_messages("快递")
    assert len(results) == 1
    assert results[0]["session_id"] == "sq"
    assert log_store.search_messages("不存在的词xyz") == []
    assert log_store.search_messages("  ") == []


def test_delete_session_removes_messages():
    log_store.record_message("sd", "user", "hello")
    assert log_store.delete_session("sd") is True
    assert log_store.get_session("sd") is None
    assert log_store.get_messages("sd") == []
    assert log_store.delete_session("sd") is False


def test_unknown_session_returns_none():
    assert log_store.get_session("nope") is None
    assert log_store.get_messages("nope") == []


def test_disabled_store_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "log_store_enabled", False, raising=False)
    log_store.record_message("s-off", "user", "hello")
    assert log_store.enabled is False
    assert log_store.list_sessions() == []
    assert log_store.get_messages("s-off") == []
    assert log_store.stats()["total_sessions"] == 0
    assert log_store.delete_session("s-off") is False


def test_init_db_idempotent():
    assert log_store.init_db() is True
    assert log_store.init_db() is True
