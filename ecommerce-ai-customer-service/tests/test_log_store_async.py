"""LogStore 异步队列 + 批量写入 + 会话恢复接口测试。"""

from __future__ import annotations

import asyncio

import pytest

from app.services.log_store import LogStore


@pytest.fixture
def fresh_store(tmp_path):
    """完全独立的 LogStore（不走单例的 init_db）。"""
    store = LogStore(db_path=tmp_path / "fresh.db")
    store.init_db()
    yield store
    # 关闭后台 worker（如果有）
    try:
        asyncio.get_event_loop().run_until_complete(store.shutdown())
    except Exception:
        pass


class TestEnqueueAndFlush:
    @pytest.mark.asyncio
    async def test_enqueue_writes_after_flush(self, fresh_store):
        await fresh_store.startup()
        try:
            for i in range(5):
                fresh_store.enqueue_message("sess1", "user", f"msg-{i}", {"intent": "other"})
            await fresh_store._flush_once()
            msgs = fresh_store.get_messages("sess1")
            assert len(msgs) == 5
        finally:
            await fresh_store.shutdown()

    @pytest.mark.asyncio
    async def test_enqueue_fallback_to_sync_when_no_queue(self, fresh_store):
        # 不调用 startup → 没有队列 → 降级同步写
        fresh_store.enqueue_message("sess2", "user", "hi", {"intent": "other"})
        msgs = fresh_store.get_messages("sess2")
        assert len(msgs) == 1

    @pytest.mark.asyncio
    async def test_batch_groups_per_session(self, fresh_store):
        await fresh_store.startup()
        try:
            for sid in ("s1", "s2"):
                for i in range(3):
                    fresh_store.enqueue_message(
                        sid, "user" if i % 2 == 0 else "assistant",
                        f"{sid}-{i}", {"intent": "x"}
                    )
            await fresh_store._flush_once()
            assert fresh_store.get_session("s1")["message_count"] == 3
            assert fresh_store.get_session("s2")["message_count"] == 3
        finally:
            await fresh_store.shutdown()

    @pytest.mark.asyncio
    async def test_pii_redaction_on_persist(self, fresh_store, monkeypatch):
        from app.config import settings as s
        monkeypatch.setattr(s, "redact_pii", True, raising=False)
        await fresh_store.startup()
        try:
            fresh_store.enqueue_message("s3", "user", "我的手机 13812345678", {"intent": "other"})
            await fresh_store._flush_once()
            msgs = fresh_store.get_messages("s3")
            assert "13812345678" not in msgs[0]["content"]
            assert "138****5678" in msgs[0]["content"]
        finally:
            await fresh_store.shutdown()


class TestListActiveSessions:
    def test_returns_recent(self, fresh_store):
        fresh_store.record_message("alive1", "user", "hi", {"intent": "x"})
        fresh_store.record_message("alive2", "user", "hi", {"intent": "x"})
        result = fresh_store.list_active_sessions()
        assert set(result) >= {"alive1", "alive2"}

    def test_empty_when_disabled(self, fresh_store, monkeypatch):
        from app.config import settings as s
        monkeypatch.setattr(s, "log_store_enabled", False, raising=False)
        assert fresh_store.list_active_sessions() == []
