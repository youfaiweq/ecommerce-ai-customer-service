"""pytest 共享夹具。

核心目标：让测试**完全离线可跑**——
    - 用假客户端替换大模型，杜绝真实网络调用
    - 每个测试使用独立的临时 SQLite 日志库
    - 默认关闭限流（限流专项测试再单独打开）
    - 清空内存中的会话历史与槽位
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services import llm_service as llm_module  # noqa: E402
from app.services.dialogue_manager import dialogue_manager  # noqa: E402
from app.services.log_store import log_store  # noqa: E402
from app.utils.rate_limit import RateLimitMiddleware  # noqa: E402


# ---------------------------------------------------------------------------
# 假 LLM 客户端（非流式）
# ---------------------------------------------------------------------------
class FakeCompletions:
    """可编程的假 chat.completions（非流式）。"""

    def __init__(self, reply: str = "（模拟回复）", intent: str = "other") -> None:
        self.reply = reply
        self.intent = intent
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        messages = kwargs.get("messages", [])
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        content = self.intent if "意图分类器" in system else self.reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeLLMClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


# ---------------------------------------------------------------------------
# 假 LLM 客户端（流式）：yield 几个 chunk
# ---------------------------------------------------------------------------
class FakeStreamingCompletions:
    """可编程的假 chat.completions（流式）。"""

    def __init__(self, chunks: list[str] | None = None) -> None:
        self.chunks = chunks or ["你", "好，", "这是", "流式", "回复"]
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)

        async def _aiter():
            for c in self.chunks:
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=c))]
                )

        # OpenAI SDK 接受 AsyncIterator
        return _aiter()


class FakeStreamingLLMClient:
    def __init__(self, completions: FakeStreamingCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


@pytest.fixture
def fake_llm(monkeypatch) -> FakeCompletions:
    fake = FakeCompletions()
    monkeypatch.setattr(llm_module.llm_service, "_async_client", FakeLLMClient(fake), raising=False)
    monkeypatch.setattr(llm_module.llm_service, "_sync_client", None, raising=False)
    return fake


@pytest.fixture
def fake_llm_factory(monkeypatch):
    def _make(reply: str = "（模拟回复）", intent: str = "other") -> FakeCompletions:
        fake = FakeCompletions(reply=reply, intent=intent)
        monkeypatch.setattr(
            llm_module.llm_service, "_async_client", FakeLLMClient(fake), raising=False
        )
        return fake
    return _make


@pytest.fixture
def fake_streaming_llm(monkeypatch):
    fake = FakeStreamingCompletions()
    monkeypatch.setattr(llm_module.llm_service, "_async_client", FakeStreamingLLMClient(fake), raising=False)
    monkeypatch.setattr(llm_module.llm_service, "_sync_client", None, raising=False)
    return fake


# ---------------------------------------------------------------------------
# 全局隔离
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    # 1. 独立的 SQLite 日志库
    monkeypatch.setattr(log_store, "_db_path", tmp_path / "test_logs.db", raising=False)
    # 清掉可能的 worker 残留（确保同步路径走 record_message）
    log_store._queue = None
    log_store._worker_task = None
    log_store._stop_event = None
    log_store.init_db()

    # 2. 默认关闭限流（限流测试自行打开）
    monkeypatch.setattr(settings, "rate_limit_enabled", False, raising=False)
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key", raising=False)
    monkeypatch.setattr(settings, "admin_api_keys", "", raising=False)
    monkeypatch.setattr(settings, "auth_secret", "test-auth-secret", raising=False)
    RateLimitMiddleware.reset_all()

    # 3. 清空内存会话与槽位
    dialogue_manager.clear_all()

    # 4. 重置 LLM 熔断器（避免测试间状态泄漏）
    llm_module.llm_service.circuit_breaker.reset()

    yield

    dialogue_manager.clear_all()
    RateLimitMiddleware.reset_all()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, headers={"X-Admin-Key": "test-admin-key"})


@pytest.fixture
def soft_client() -> TestClient:
    return TestClient(
        app,
        raise_server_exceptions=False,
        headers={"X-Admin-Key": "test-admin-key"},
    )


# ---------------------------------------------------------------------------
# 鉴权夹具：直接签发 token，不走 /auth/login HTTP 路径，便于快速跑业务测试
# ---------------------------------------------------------------------------
from app.auth.tokens import create_token  # noqa: E402


@pytest.fixture
def make_token() -> str:
    """token 工厂：传入 user_id 即得到 Bearer token 字符串。"""
    def _make(user_id: str = "u1001") -> str:
        return create_token(user_id)
    return _make


@pytest.fixture
def auth_token() -> str:
    """默认 u1001 的 token 字符串。"""
    return create_token("u1001")


@pytest.fixture
def auth_headers(auth_token) -> dict[str, str]:
    """默认 u1001 的 Authorization 头。"""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def auth_headers_u1002(make_token) -> dict[str, str]:
    """u1002 的 Authorization 头（用于跨用户越权测试）。"""
    return {"Authorization": f"Bearer {make_token('u1002')}"}


@pytest.fixture
def prod_client():
    """模拟生产模式（debug=False）的客户端。"""
    original_debug = app.debug
    app.debug = False
    app.middleware_stack = None
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.debug = original_debug
        app.middleware_stack = None


# ---------------------------------------------------------------------------
# 异步事件循环：让 pytest 认识 async 测试
# ---------------------------------------------------------------------------
@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
