"""限流中间件（内存滑动窗口，按客户端 IP）。

特点：
    - 零依赖：仅用标准库，基于「滑动窗口 + 时间戳队列」实现
    - 免限流路径可配置（健康检查、文档、静态资源等）
    - 超限返回 429，并带 ``Retry-After`` 响应头
    - 仅单进程有效；多实例部署需改用 Redis 等集中式限流

安全提示：
    默认**不信任** ``X-Forwarded-For``（客户端可伪造以绕过限流）。
    部署在可信反向代理之后时，可通过 ``TRUST_FORWARDED_FOR=true`` 开启。

实现说明：
    计数状态放在**类级**共享（同进程内所有实例共用一份），
    这样即使 Starlette 在内部构造中间件实例，也能通过
    ``RateLimitMiddleware.reset_all()`` 统一复位——便于测试。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)


def _compile_exempt_patterns(paths: list[str]) -> list[re.Pattern[str]]:
    """把路径前缀列表编译成正则。

    支持三种写法：
        - `/health`      → 匹配 `/health` 与 `/health/...` 与 `/healthcheck` ← 会被前缀匹配误中
        - 改为正则锚定：`/health(/.*)?$` 只匹配 `/health` 与 `/health/...`
    实际配置中已加 `$` 锚定（如 `/health$,/health/deep$,...`），但为保险再加一次。
    """
    patterns: list[re.Pattern[str]] = []
    for p in paths:
        # 转义 regex 特殊字符，但保留 `/`
        escaped = re.escape(p)
        # 配置里的 `/health` 等价于 `^/health($|/.*)`：精确匹配或子路径
        if escaped.endswith("\\$"):
            # 已经带了 $，去掉再补成完整锚定
            escaped = escaped[:-2]
            patterns.append(re.compile(f"^{escaped}(?:/.*)?$"))
        else:
            patterns.append(re.compile(f"^{escaped}(?:/.*)?$"))
    return patterns


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于滑动窗口的限流中间件。

    :param requests_per_window: 窗口内允许的请求数；None 时取配置
    :param window_seconds: 窗口长度（秒）；None 时取配置
    :param exempt_paths: 免限流路径前缀；None 时取配置
    """

    # 共享状态：client_key -> 请求时间戳队列
    _hits: dict[str, deque] = defaultdict(deque)
    _lock = threading.Lock()
    _max_tracked_clients = 10_000

    def __init__(
        self,
        app,
        requests_per_window: int | None = None,
        window_seconds: int | None = None,
        exempt_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._limit = requests_per_window
        self._window = window_seconds
        self._exempt = exempt_paths
        # 编译好的正则（按路径列表缓存）
        self._exempt_patterns = _compile_exempt_patterns(self.exempt_paths)

    # ------------------------------------------------------------------
    @property
    def limit(self) -> int:
        return self._limit if self._limit is not None else settings.rate_limit_requests

    @property
    def window(self) -> int:
        return self._window if self._window is not None else settings.rate_limit_window

    @property
    def exempt_paths(self) -> list[str]:
        return self._exempt if self._exempt is not None else settings.rate_limit_exempt_list

    # ------------------------------------------------------------------
    @staticmethod
    def client_key(request: Request) -> str:
        """识别客户端：默认用连接 IP，可选信任 X-Forwarded-For。"""
        if settings.trust_forwarded_for:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _is_exempt(self, path: str) -> bool:
        """正则精确匹配：避免 `/health` 误命中 `/healthcheck`。"""
        return any(p.match(path) for p in self._exempt_patterns)

    @staticmethod
    def _limits_for_path(path: str) -> tuple[int, int, str]:
        """登录使用单独、更严格的窗口，其余接口沿用全局限流。"""
        if path == "/auth/login":
            return (
                settings.login_rate_limit_requests,
                settings.login_rate_limit_window,
                "login",
            )
        return settings.rate_limit_requests, settings.rate_limit_window, "api"

    # ------------------------------------------------------------------
    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled or self._is_exempt(request.url.path):
            return await call_next(request)
        if request.url.path == "/auth/login" and not settings.login_rate_limit_enabled:
            return await call_next(request)

        limit, window, bucket_type = self._limits_for_path(request.url.path)
        if self._limit is not None:
            limit = self._limit
        if self._window is not None:
            window = self._window
        key = f"{bucket_type}:{self.client_key(request)}"
        now = time.monotonic()

        with RateLimitMiddleware._lock:
            bucket = RateLimitMiddleware._hits[key]
            # 丢弃窗口外的历史记录
            while bucket and now - bucket[0] > window:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(window - (now - bucket[0])) + 1)
                logger.warning("触发限流：client=%s path=%s", key, request.url.path)
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    content={
                        "error": {
                            "code": "rate_limited",
                            "message": (
                                f"请求过于频繁，请 {retry_after} 秒后重试"
                                f"（当前限制：{limit} 次 / {window} 秒）"
                            ),
                        }
                    },
                )

            bucket.append(now)
            self._prune_locked(now)

        return await call_next(request)

    # ------------------------------------------------------------------
    @classmethod
    def _prune_locked(cls, now: float) -> None:
        """清理长期无请求的客户端记录，避免内存无限增长。"""
        if len(cls._hits) <= cls._max_tracked_clients:
            return
        stale = [
            key for key, q in cls._hits.items() if not q or now - q[-1] > 300
        ]
        for key in stale:
            cls._hits.pop(key, None)

    @classmethod
    def reset_all(cls) -> None:
        """清空全部限流计数（供测试使用）。"""
        with cls._lock:
            cls._hits.clear()

    def reset(self) -> None:
        """实例级便捷方法，等价于 ``reset_all()``。"""
        RateLimitMiddleware.reset_all()
