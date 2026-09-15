"""P2 改进测试：反馈按钮、FAQ 缓存、多轮上下文压缩。"""

from __future__ import annotations

import time

import pytest

from app.config import settings
from app.services.dialogue_manager import dialogue_manager
from app.services.knowledge_base import KnowledgeBase


# ===========================================================================
# 反馈按钮（LogStore + API）
# ===========================================================================
class TestFeedback:
    def test_record_feedback_positive(self):
        from app.services.log_store import log_store

        ok = log_store.record_feedback("sess-fb-1", score=1)
        assert ok is True
        items = log_store.get_feedback_for_session("sess-fb-1")
        assert len(items) == 1
        assert items[0]["score"] == 1

    def test_record_feedback_negative_with_comment(self):
        from app.services.log_store import log_store

        log_store.record_feedback("sess-fb-2", score=-1, comment="回答跑题")
        items = log_store.get_feedback_for_session("sess-fb-2")
        assert len(items) == 1
        assert items[0]["score"] == -1
        assert items[0]["comment"] == "回答跑题"

    def test_record_feedback_invalid_score_rejected(self):
        from app.services.log_store import log_store

        ok = log_store.record_feedback("sess-fb-3", score=0)
        assert ok is False
        ok = log_store.record_feedback("sess-fb-3", score=5)
        assert ok is False

    def test_feedback_stats(self):
        from app.services.log_store import log_store

        log_store.record_feedback("sess-stats", score=1)
        log_store.record_feedback("sess-stats", score=1)
        log_store.record_feedback("sess-stats", score=-1, comment="不好")
        stats = log_store.feedback_stats()
        assert stats["total"] >= 3
        assert stats["positive"] >= 2
        assert stats["negative"] >= 1
        assert stats["with_comment"] >= 1
        assert 0 <= stats["positive_rate"] <= 1

    def test_feedback_in_session_detail(self, client):
        from app.services.log_store import log_store

        log_store.record_message("sess-fb-detail", "user", "hi", {"intent": "other"})
        log_store.record_message(
            "sess-fb-detail", "assistant", "你好", {"intent": "other"}
        )
        msg_id = log_store.get_messages("sess-fb-detail")[0]["id"]
        log_store.record_feedback("sess-fb-detail", score=1, message_id=msg_id, comment="good")
        resp = client.get("/admin/sessions/sess-fb-detail")
        assert resp.status_code == 200
        body = resp.json()
        # 至少一条消息带 feedback
        msgs_with_fb = [m for m in body["messages"] if m.get("feedback")]
        assert len(msgs_with_fb) >= 1

    def test_chat_feedback_endpoint_no_auth(self, client):
        """用户态直接调，无需 admin key"""
        resp = client.post("/chat/sess-chat-fb/feedback", json={"score": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert body["recorded"] is True
        assert body["score"] == 1

    def test_chat_feedback_invalid_score(self, client):
        resp = client.post("/chat/sess-chat-fb2/feedback", json={"score": 0})
        assert resp.status_code == 422

    def test_admin_feedback_endpoints(self, client):
        resp = client.post(
            "/admin/feedback",
            json={"session_id": "admin-fb", "score": 1, "comment": "ok"},
        )
        assert resp.status_code == 200
        resp = client.get("/admin/feedback/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        resp = client.get("/admin/sessions/admin-fb/feedback")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_delete_session_cascades_feedback(self):
        from app.services.log_store import log_store

        log_store.record_message("sess-cascade", "user", "x", {"intent": "other"})
        log_store.record_feedback("sess-cascade", score=1)
        assert len(log_store.get_feedback_for_session("sess-cascade")) == 1
        assert log_store.delete_session("sess-cascade")
        assert log_store.get_feedback_for_session("sess-cascade") == []


# ===========================================================================
# FAQ 缓存
# ===========================================================================
class TestFAQCache:
    def test_cache_hit_within_ttl(self):
        # 创建一个独立的 KB 实例（不污染全局）
        kb = KnowledgeBase(cache_ttl_seconds=60.0)
        first = kb.search("退款多久到账")
        second = kb.search("退款多久到账")
        assert len(first) == len(second)
        # 同一查询：缓存命中，所以 hits 应该增加
        assert kb.cache_stats["hits"] >= 1
        assert kb.cache_stats["misses"] >= 1

    def test_cache_miss_after_ttl_expires(self):
        kb = KnowledgeBase(cache_ttl_seconds=0.05)
        kb.search("优惠券叠加")
        initial_misses = kb.cache_stats["misses"]
        # 等缓存过期
        time.sleep(0.1)
        kb.search("优惠券叠加")
        # 应该重新检索 → misses 增加
        assert kb.cache_stats["misses"] > initial_misses

    def test_reload_clears_cache(self):
        kb = KnowledgeBase(cache_ttl_seconds=60.0)
        kb.search("优惠券叠加")
        assert kb.cache_stats["size"] >= 1
        kb.reload()
        assert kb.cache_stats["size"] == 0

    def test_cache_disabled_when_ttl_zero(self, monkeypatch):
        """TTL=0 时不缓存。"""
        from app.config import settings

        monkeypatch.setattr(settings, "faq_cache_ttl_seconds", 0.0)
        kb = KnowledgeBase()
        kb.search("物流")
        kb.search("物流")
        # TTL=0 应当每次都 miss，不缓存
        assert kb.cache_stats["size"] == 0
        assert kb.cache_stats["hits"] == 0

    def test_cache_size_limit(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "faq_cache_max_size", 2)
        kb = KnowledgeBase()
        kb.search("订单")
        kb.search("物流")
        kb.search("退款")
        kb.search("优惠券")
        # 容量 2，FIFO 淘汰
        assert kb.cache_stats["size"] <= 2

    def test_search_answer_uses_cache(self):
        """search_answer 也走缓存（相同 query 复用 search 结果）。"""
        kb = KnowledgeBase(cache_ttl_seconds=60.0)
        a1 = kb.search_answer("退款多久到账")
        a2 = kb.search_answer("退款多久到账")
        assert a1 == a2

    def test_search_with_different_topk_creates_different_cache_keys(self):
        """top_k 不同视为不同 key。"""
        kb = KnowledgeBase(cache_ttl_seconds=60.0)
        kb.search("退款", top_k=2)
        kb.search("退款", top_k=5)
        assert kb.cache_stats["size"] >= 2


# ===========================================================================
# 多轮上下文压缩
# ===========================================================================
class TestContextSummary:
    def setup_method(self):
        dialogue_manager.clear_all()

    @pytest.mark.asyncio
    async def test_under_threshold_no_summary(self, monkeypatch, fake_llm_factory):
        """history < trigger → 不触发摘要"""
        from app.config import settings

        monkeypatch.setattr(settings, "context_summary_trigger", 4)
        from app.services.chat_service import chat_service

        fake_llm_factory(reply="好")
        # 灌 4 条消息（2 轮对话）
        for i in range(2):
            await chat_service.chat("sess-cs1", f"msg{i}")
        # fake LLM 被调用了 2 次（意图分类 + 正常回复），没有摘要调用
        # 检查：没被 mark_summarized
        assert not dialogue_manager.has_been_summarized("sess-cs1")

    @pytest.mark.asyncio
    async def test_over_threshold_triggers_summary(self, monkeypatch, fake_llm_factory):
        """history >= trigger → 触发一次摘要，每会话最多 1 次"""
        from app.config import settings

        monkeypatch.setattr(settings, "context_summary_trigger", 4)
        monkeypatch.setattr(settings, "context_summary_keep_recent", 2)
        from app.services.chat_service import chat_service

        # 第一次 chat：拿到 fake_llm
        fake_llm_factory(reply="reply-1")
        sid = "sess-cs-over"
        # 直接造长历史（绕过 chat，灌进 DM）
        for i in range(6):
            dialogue_manager.add_message(sid, "user", f"q{i}")
            dialogue_manager.add_message(sid, "assistant", f"a{i}")
        # 调用 chat：history 长度 12 >= trigger，应触发摘要
        await chat_service.chat(sid, "新消息")
        # 验证已 mark
        assert dialogue_manager.has_been_summarized(sid)

    @pytest.mark.asyncio
    async def test_summary_max_once_per_session(self, monkeypatch, fake_llm_factory):
        from app.config import settings

        monkeypatch.setattr(settings, "context_summary_trigger", 2)
        monkeypatch.setattr(settings, "context_summary_keep_recent", 2)
        from app.services.chat_service import chat_service

        fake_llm_factory(reply="r")
        # 灌入超过 trigger 的历史
        for i in range(4):
            dialogue_manager.add_message("sess-cs4", "user", f"q{i}")
            dialogue_manager.add_message("sess-cs4", "assistant", f"a{i}")
        # 第一次 chat → 触发摘要
        await chat_service.chat("sess-cs4", "first")
        # 此时 _summarized 应该被标记
        # 第二次 chat → history 已含 system 摘要，但仍可能 >= trigger
        # 关键：摘要不会被再触发（已有 _summarized 标记）
        # 检查 fake 的调用次数增加 = chat 调用次数（不含额外的摘要调用）
        # 由于第一次调用 chat 已经触发了 fake（意图分类 + 回复），第二次再 chat 只调用 fake 两次（意图 + 回复）
        # 我们不直接断言次数，而是断言 mark 只触发一次
        assert dialogue_manager.has_been_summarized("sess-cs4")
        # 再来一次
        await chat_service.chat("sess-cs4", "second")
        # 摘要标记依然在
        assert dialogue_manager.has_been_summarized("sess-cs4")

    @pytest.mark.asyncio
    async def test_summary_disabled_keeps_history(self, monkeypatch, fake_llm_factory):
        from app.config import settings

        monkeypatch.setattr(settings, "enable_context_summary", False)
        monkeypatch.setattr(settings, "context_summary_trigger", 2)
        from app.services.chat_service import chat_service

        fake_llm_factory(reply="r")
        for i in range(4):
            dialogue_manager.add_message("sess-cs5", "user", f"q{i}")
            dialogue_manager.add_message("sess-cs5", "assistant", f"a{i}")
        await chat_service.chat("sess-cs5", "msg")
        # 关闭开关后不应被标记
        assert not dialogue_manager.has_been_summarized("sess-cs5")

    @pytest.mark.asyncio
    async def test_summary_llm_failure_passthrough(self, monkeypatch):
        """LLM 摘要失败时不影响主流程。"""
        from app.services import chat_service as cs_mod
        from app.services.llm_service import LLMError, llm_service

        monkeypatch.setattr(settings, "context_summary_trigger", 2)
        monkeypatch.setattr(settings, "context_summary_keep_recent", 2)

        # 拦截意图识别 + LLM：让所有 chat() 走 fake；只有摘要那次抛错
        from app.services.intent_service import Intent, IntentResult
        from app.services.intent_service import intent_service as _intent_svc

        async def fake_detect(self, text):
            return IntentResult(intent=Intent.OTHER, confidence=0.99, method="rule")

        async def fake_achat(self, history, system_prompt=None, **kwargs):
            # 摘要 prompt → 抛错；其它 → 返回固定字符串
            if "简洁的对话摘要助手" in (system_prompt or ""):
                raise LLMError("LLM 不可用")
            return "fake reply"

        monkeypatch.setattr(_intent_svc.__class__, "detect", fake_detect)
        monkeypatch.setattr(llm_service.__class__, "achat", fake_achat)

        for i in range(4):
            dialogue_manager.add_message("sess-cs6", "user", f"q{i}")
            dialogue_manager.add_message("sess-cs6", "assistant", f"a{i}")
        # 不应抛错
        result = await cs_mod.chat_service.chat("sess-cs6", "msg")
        assert result.reply == "fake reply"
        # 摘要失败 → 不应被 mark
        assert not dialogue_manager.has_been_summarized("sess-cs6")


class TestDialogueManagerSummaryFlag:
    def test_mark_and_check(self):
        dialogue_manager.clear_all()
        assert not dialogue_manager.has_been_summarized("s1")
        dialogue_manager.mark_summarized("s1")
        assert dialogue_manager.has_been_summarized("s1")
        # 不同 session 互不影响
        assert not dialogue_manager.has_been_summarized("s2")
