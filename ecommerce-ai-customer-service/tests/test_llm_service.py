"""LLM 服务：重试 + 熔断 + 流式测试。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from openai import APIConnectionError

from app.services.llm_service import (
    CircuitBreaker,
    CircuitOpenError,
    LLMService,
)


def _api_conn_error(msg: str = "net") -> APIConnectionError:
    """构造一个 APIConnectionError（OpenAI v1 SDK 需要 request 参数）。"""
    mock_req = MagicMock()
    return APIConnectionError(request=mock_req)


def _auth_error() -> Exception:
    """构造一个 AuthenticationError（避免真实网络）。"""
    from openai import AuthenticationError
    mock_req = MagicMock()
    mock_resp = MagicMock()
    mock_resp.request = mock_req
    return AuthenticationError("bad key", response=mock_resp, body=None)


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------
class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_closed_then_open_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout_s=1.0)
        async def boom():
            raise _api_conn_error()
        for _ in range(3):
            with pytest.raises(APIConnectionError):
                await cb.call(boom)
        # 第 4 次直接拒绝
        with pytest.raises(CircuitOpenError):
            await cb.call(boom)
        assert cb.state._state == "open"

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.1)
        async def boom():
            raise _api_conn_error()
        with pytest.raises(APIConnectionError):
            await cb.call(boom)
        await asyncio.sleep(0.15)
        # 半开探测：再次调用成功 → closed
        async def ok():
            return "ok"
        assert await cb.call(ok) == "ok"
        assert cb.state._state == "closed"

    @pytest.mark.asyncio
    async def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout_s=1.0)
        async def boom():
            raise _api_conn_error()
        with pytest.raises(APIConnectionError):
            await cb.call(boom)
        cb.reset()
        assert cb.state._state == "closed"


# ---------------------------------------------------------------------------
# 重试
# ---------------------------------------------------------------------------
class TestRetry:
    @pytest.mark.asyncio
    async def test_retry_succeed_after_one_fail(self, monkeypatch):
        from app.services import llm_service as m
        attempts = {"n": 0}

        async def fake_call_once(self, messages):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise _api_conn_error()
            return "ok"

        monkeypatch.setattr(LLMService, "_call_once_async", fake_call_once)
        monkeypatch.setattr(m.llm_service, "_async_client", None)
        # 把熔断阈值调大，避免被熔断
        monkeypatch.setattr(m.llm_service.circuit_breaker.state, "failure_threshold", 99)
        # 直接用底层装饰过的方法
        result = await m.llm_service.achat([])
        assert result == "ok"
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_fatal(self, monkeypatch):
        """致命错误（401/400）不触发重试，立即抛出。"""
        from openai import AuthenticationError

        from app.services import llm_service as m

        attempts = {"n": 0}

        async def fake_call_once(self, messages):
            attempts["n"] += 1
            mock_req = MagicMock()
            mock_resp = MagicMock()
            mock_resp.request = mock_req
            raise AuthenticationError("bad key", response=mock_resp, body=None)

        monkeypatch.setattr(LLMService, "_call_once_async", fake_call_once)
        monkeypatch.setattr(m.llm_service, "_async_client", None)
        # 用更短的重试间隔，避免测试耗时
        monkeypatch.setattr(m.llm_service, "retry_attempts", 3)
        monkeypatch.setattr(m.llm_service, "retry_base_delay", 0.01)

        with pytest.raises(AuthenticationError):
            await m.llm_service.achat([])
        # 重试装饰器遇到 _FATAL_EXC 应该立即抛出，不重试
        assert attempts["n"] == 1


# ---------------------------------------------------------------------------
# 流式
# ---------------------------------------------------------------------------
class TestStream:
    @pytest.mark.asyncio
    async def test_astream_chat_yields_chunks(self, monkeypatch):
        from app.services import llm_service as m

        async def fake_call_stream(self, messages):
            for c in ["你", "好，", "流式"]:
                yield c

        monkeypatch.setattr(LLMService, "_call_stream_async", fake_call_stream)
        monkeypatch.setattr(m.llm_service, "_async_client", None)

        chunks: list[str] = []
        async for delta in m.llm_service.astream_chat([{"role": "user", "content": "hi"}]):
            chunks.append(delta)
        assert "".join(chunks) == "你好，流式"
