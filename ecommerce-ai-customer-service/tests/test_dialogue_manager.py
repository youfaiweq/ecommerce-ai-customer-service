"""会话历史与槽位管理测试。"""

from __future__ import annotations

import pytest

from app.services.dialogue_manager import DialogueManager


@pytest.fixture
def dm() -> DialogueManager:
    return DialogueManager(max_messages=4, max_sessions=2)


def test_new_session_id_unique_and_hex():
    a, b = DialogueManager.new_session_id(), DialogueManager.new_session_id()
    assert a != b
    assert len(a) == 32
    int(a, 16)  # 可解析为十六进制


def test_add_and_get_history(dm):
    sid = dm.new_session_id()
    dm.add_user_message(sid, "你好")
    dm.add_assistant_message(sid, "您好")
    history = dm.get_history(sid)
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "你好"
    assert dm.message_count(sid) == 2


def test_get_history_returns_copy(dm):
    sid = dm.new_session_id()
    dm.add_user_message(sid, "你好")
    history = dm.get_history(sid)
    history.append({"role": "user", "content": "篡改"})
    assert dm.message_count(sid) == 1  # 内部状态未被污染


def test_get_history_unknown_session_returns_empty(dm):
    assert dm.get_history("not-exist") == []
    assert dm.message_count("not-exist") == 0


def test_invalid_role_raises(dm):
    with pytest.raises(ValueError):
        dm.add_message("s1", "bogus", "x")


def test_history_trimming(dm):
    sid = dm.new_session_id()
    for i in range(6):
        dm.add_message(sid, "user", f"m{i}")
    history = dm.get_history(sid)
    assert len(history) == 4  # max_messages=4
    assert [m["content"] for m in history] == ["m2", "m3", "m4", "m5"]  # 保留最近的


def test_clear_history(dm):
    sid = dm.new_session_id()
    dm.add_user_message(sid, "你好")
    assert dm.clear_history(sid) is True
    assert dm.message_count(sid) == 0
    assert dm.session_exists(sid) is True  # 会话仍在，只是消息清空
    assert dm.clear_history("not-exist") is False


def test_delete_session(dm):
    sid = dm.new_session_id()
    dm.add_user_message(sid, "你好")
    dm.set_slot(sid, "order_no", "202609030002")
    assert dm.delete_session(sid) is True
    assert dm.session_exists(sid) is False
    assert dm.get_slot(sid, "order_no") is None  # 槽位一并清理
    assert dm.delete_session(sid) is False


# ----------------------------------------------------------------------
# 槽位
# ----------------------------------------------------------------------
def test_slots_set_get_clear(dm):
    sid = dm.new_session_id()
    assert dm.get_slot(sid, "order_no") is None
    dm.set_slot(sid, "order_no", "202609030002")
    assert dm.get_slot(sid, "order_no") == "202609030002"
    assert dm.get_slots(sid) == {"order_no": "202609030002"}
    dm.clear_slots(sid)
    assert dm.get_slots(sid) == {}


def test_slot_default_value(dm):
    assert dm.get_slot("nope", "order_no", "fallback") == "fallback"


# ----------------------------------------------------------------------
# LRU
# ----------------------------------------------------------------------
def test_lru_eviction_of_sessions(dm):
    a, b, c = (dm.new_session_id() for _ in range(3))
    dm.add_user_message(a, "a")
    dm.add_user_message(b, "b")
    dm.add_user_message(c, "c")  # 超出 max_sessions=2 → 淘汰最久未用的 a
    sessions = dm.list_sessions()
    assert len(sessions) == 2
    assert a not in sessions
    assert sessions[-1] == c  # 最近使用在末尾


def test_lru_touch_on_access(dm):
    a, b, c = (dm.new_session_id() for _ in range(3))
    dm.add_user_message(a, "a")
    dm.add_user_message(b, "b")
    dm.get_history(a)  # 访问 a → a 变为最近使用
    dm.add_user_message(c, "c")  # 应淘汰 b 而不是 a
    sessions = dm.list_sessions()
    assert a in sessions and b not in sessions


def test_list_sessions_order(dm):
    a, b = dm.new_session_id(), dm.new_session_id()
    dm.add_user_message(a, "a")
    dm.add_user_message(b, "b")
    assert dm.list_sessions() == [a, b]


def test_clear_all(dm):
    dm.add_user_message("s1", "x")
    dm.set_slot("s1", "order_no", "1")
    dm.clear_all()
    assert dm.list_sessions() == []
    assert dm.get_slots("s1") == {}
