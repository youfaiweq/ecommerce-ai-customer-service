"""大模型服务（LLM Service）。

封装 OpenAI 兼容接口，可对接：
    - 官方 OpenAI
    - 本地 Ollama（OPENAI_BASE_URL=http://localhost:11434/v1）
    - 各类兼容 OpenAI 协议的第三方服务（DeepSeek / 通义千问 等）

对外提供：
    - chat()         同步调用
    - achat()        异步调用（供 FastAPI 异步路由使用）
    - astream_chat() 异步流式调用（token-by-token，yield 增量字符串）
均支持传入对话历史（list of messages）与自定义 system prompt。

P0 加固：
    * 指数退避重试（tenacity）—— 只针对可恢复错误（429 / 5xx / 超时 / 连接错）
    * 进程级轻量熔断器 —— 连续失败达到阈值熔断，避免雪崩
    * 流式响应走独立实现，不受熔断开关影响
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)

from app.config import settings
from app.utils.logging import bind_context, log_event, measure_ms

logger = logging.getLogger(__name__)

# 默认系统提示词：电商智能客服角色设定
DEFAULT_SYSTEM_PROMPT = (
    "你是一名专业、友好的电商平台智能客服助手。"
    "请用简洁、礼貌的中文回答用户关于订单、物流、退换货、优惠、支付等方面的问题。"
    "如果不确定，请引导用户补充信息，或建议其联系人工客服。"
)

# 浏览器只能从这份白名单中选择服务商，不能传入 URL、模型名或 API Key。
LLM_PROVIDERS = ("deepseek", "ollama")

# 允许的角色
VALID_ROLES = ("system", "user", "assistant")

# 可恢复错误（用于区分重试与快速失败）
_RETRYABLE_EXC: tuple[type[BaseException], ...] = (
    RateLimitError,
    APIConnectionError,
    APITimeoutError,
    TimeoutError,
)

# 不可恢复错误（直接抛出，不重试）
_FATAL_EXC: tuple[type[BaseException], ...] = (
    AuthenticationError,  # 401 / 403 不会自愈
    BadRequestError,      # 400 提示词/参数问题，重试无意义
)


# ---------------------------------------------------------------------------
# 熔断器
# ---------------------------------------------------------------------------
class CircuitOpenError(RuntimeError):
    """熔断器处于打开状态时抛出。"""


@dataclass
class CircuitState:
    failure_threshold: int = 5
    reset_timeout_s: float = 30.0
    _fail_count: int = 0
    _opened_at: float = 0.0
    _state: str = "closed"  # closed / open / half_open


class CircuitBreaker:
    """进程内轻量熔断器（线程/协程安全）。

    状态机：
        closed —— 正常放行；连续失败累计达阈值 → open
        open   —— 立即拒绝；冷却 `reset_timeout_s` 后 → half_open
        half_open —— 放行 1 次探测；成功 → closed；失败 → open
    """

    def __init__(self, *, failure_threshold: int = 5, reset_timeout_s: float = 30.0) -> None:
        self.state = CircuitState(
            failure_threshold=failure_threshold,
            reset_timeout_s=reset_timeout_s,
        )
        self._lock = asyncio.Lock()

    def _snapshot(self) -> CircuitState:
        return self.state

    async def call(self, func, /, *args, **kwargs):
        """执行可调用对象，受熔断策略保护。"""
        async with self._lock:
            s = self._snapshot()
            if s._state == "open":
                if time.monotonic() - s._opened_at >= s.reset_timeout_s:
                    s._state = "half_open"
                    log_event("circuit.half_open")
                else:
                    raise CircuitOpenError(
                        f"熔断中：剩余 {(s.reset_timeout_s - (time.monotonic() - s._opened_at)):.1f}s"
                    )
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
        except Exception:
            async with self._lock:
                s = self._snapshot()
                s._fail_count += 1
                if s._state == "half_open" or s._fail_count >= s.failure_threshold:
                    if s._state != "open":
                        s._state = "open"
                        s._opened_at = time.monotonic()
                        log_event(
                            "circuit.open",
                            fail_count=s._fail_count,
                            threshold=s.failure_threshold,
                        )
            raise
        async with self._lock:
            s = self._snapshot()
            if s._state == "half_open":
                log_event("circuit.closed_after_probe")
            s._state = "closed"
            s._fail_count = 0
        log_event("llm.success", latency_ms=measure_ms(start))
        return result

    def reset(self) -> None:
        self.state._fail_count = 0
        self.state._state = "closed"
        self.state._opened_at = 0.0


# ---------------------------------------------------------------------------
# 重试装饰器（无 tenacity 依赖，纯 stdlib）
# ---------------------------------------------------------------------------
def retry_async(
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
    retryable: tuple[type[BaseException], ...] = _RETRYABLE_EXC,
):
    """对异步函数做指数退避重试。"""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_exc: BaseException | None = None
            for i in range(attempts):
                try:
                    return await func(*args, **kwargs)
                except retryable as exc:
                    last_exc = exc
                    if i == attempts - 1:
                        break
                    delay = min(max_delay, base_delay * (2 ** i))
                    log_event(
                        "llm.retry",
                        attempt=i + 1,
                        max=attempts,
                        delay_s=round(delay, 2),
                        error_type=type(exc).__name__,
                        error=str(exc)[:120],
                    )
                    await asyncio.sleep(delay)
                except _FATAL_EXC:
                    raise
            assert last_exc is not None
            raise last_exc
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 主服务类
# ---------------------------------------------------------------------------
class LLMError(RuntimeError):
    """大模型调用相关异常。"""


class LLMService:
    """OpenAI 兼容大模型服务封装。"""

    def __init__(
        self,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        *,
        retry_attempts: int | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.model = model or settings.model_name
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.base_url = base_url or settings.openai_base_url
        self.temperature = settings.temperature
        self.max_tokens = settings.max_tokens
        self.timeout = settings.request_timeout
        self._sync_client: OpenAI | None = None
        self._async_client: AsyncOpenAI | None = None

        self.retry_attempts = retry_attempts or settings.llm_retry_attempts
        self.retry_base_delay = settings.llm_retry_base_delay
        self.retry_max_delay = settings.llm_retry_max_delay
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=settings.llm_circuit_threshold,
            reset_timeout_s=settings.llm_circuit_reset_s,
        )

    # ------------------------------------------------------------------
    # 客户端
    # ------------------------------------------------------------------
    @property
    def sync_client(self) -> OpenAI:
        if self._sync_client is None:
            self._sync_client = OpenAI(
                api_key=self.api_key or "not-needed",
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._sync_client

    @property
    def async_client(self) -> AsyncOpenAI:
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=self.api_key or "not-needed",
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._async_client

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def build_messages(
        self,
        history: Iterable[Mapping[str, str]] | None,
        system_prompt: str | None = None,
    ) -> list[dict[str, str]]:
        sys_prompt = self.system_prompt if system_prompt is None else system_prompt
        messages: list[dict[str, str]] = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        for item in history or []:
            role = str(item.get("role", "")).strip()
            content = item.get("content")
            if role in VALID_ROLES and content:
                messages.append({"role": role, "content": str(content)})
        return messages

    @staticmethod
    def _extract_content(response) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMError("大模型返回格式异常，无法解析内容") from exc
        return content or ""

    # ------------------------------------------------------------------
    # 内部：单次 API 调用（可能被重试 + 熔断包裹）
    # ------------------------------------------------------------------
    async def _call_once_async(self, messages: list[dict[str, str]]) -> str:
        bind_context(model=self.model)
        try:
            response = await self.async_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except _FATAL_EXC as exc:
            log_event("llm.fatal_error", error_type=type(exc).__name__, error=str(exc)[:120])
            raise LLMError(f"调用大模型失败（不可恢复）：{exc}") from exc
        except _RETRYABLE_EXC:
            raise  # 让重试装饰器处理
        except Exception as exc:
            log_event("llm.unexpected", error_type=type(exc).__name__, error=str(exc)[:120])
            raise LLMError(f"调用大模型失败：{exc}") from exc
        return self._extract_content(response)

    async def _call_stream_async(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        bind_context(model=self.model)
        try:
            response = await self.async_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )
        except _FATAL_EXC as exc:
            raise LLMError(f"流式调用大模型失败（不可恢复）：{exc}") from exc
        except Exception as exc:
            raise LLMError(f"流式调用大模型失败：{exc}") from exc
        async for chunk in response:
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError, TypeError):
                delta = None
            if delta:
                yield delta

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def chat(
        self,
        history: Iterable[Mapping[str, str]] | None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        messages = self.build_messages(history, system_prompt)
        try:
            response = self.sync_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature if temperature is None else temperature,
                max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            )
        except _FATAL_EXC as exc:
            raise LLMError(f"调用大模型失败（不可恢复）：{exc}") from exc
        except Exception as exc:
            raise LLMError(f"调用大模型失败：{exc}") from exc
        return self._extract_content(response)

    @retry_async(
        attempts=settings.llm_retry_attempts,
        base_delay=settings.llm_retry_base_delay,
        max_delay=settings.llm_retry_max_delay,
    )
    async def achat(
        self,
        history: Iterable[Mapping[str, str]] | None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """异步对话：重试 + 熔断 双层保护。"""
        messages = self.build_messages(history, system_prompt)
        try:
            return await self.circuit_breaker.call(self._call_once_async, messages)
        except CircuitOpenError as exc:
            raise LLMError(f"大模型服务暂时不可用：{exc}") from exc

    async def astream_chat(
        self,
        history: Iterable[Mapping[str, str]] | None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """异步流式对话：token-by-token yield。失败时不重试整段（用户体验差），
        但仍受熔断保护；首块之前出现错误则整体失败。"""
        messages = self.build_messages(history, system_prompt)
        try:
            iterator = await self.circuit_breaker.call(self._call_stream_async, messages)
        except CircuitOpenError as exc:
            raise LLMError(f"大模型服务暂时不可用：{exc}") from exc
        async for delta in iterator:
            yield delta


# 模块级单例
llm_service = LLMService()

# DeepSeek 沿用既有 OPENAI_* 配置，保持现有部署完全兼容。Ollama 独立实例，
# 以免一次请求切换模型时污染另一条并发请求的客户端或熔断状态。
_provider_services: dict[str, LLMService] = {"deepseek": llm_service}


def get_llm_service(provider: str | None = None) -> LLMService:
    """返回白名单内的模型客户端；不接受来自客户端的任意连接参数。"""
    selected = (provider or "deepseek").strip().lower()
    if selected not in LLM_PROVIDERS:
        raise ValueError(f"不支持的模型服务商: {selected}")
    if selected == "deepseek":
        return llm_service
    if selected not in _provider_services:
        _provider_services[selected] = LLMService(
            model=settings.ollama_model_name,
            api_key="ollama",
            base_url=settings.ollama_base_url,
        )
    return _provider_services[selected]

__all__ = [
    "LLMService",
    "LLMError",
    "CircuitBreaker",
    "CircuitOpenError",
    "llm_service",
    "get_llm_service",
    "LLM_PROVIDERS",
    "DEFAULT_SYSTEM_PROMPT",
]
