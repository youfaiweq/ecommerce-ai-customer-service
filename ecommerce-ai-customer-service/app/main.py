"""FastAPI 应用入口。

启动方式：
    uvicorn app.main:app --reload
或：
    python -m app.main
"""

import time
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.audio import router as audio_router

# 鉴权：登录 / 当前用户 / 登出（HMAC token，详见 app/api/auth.py）
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.knowledge import router as knowledge_router
from app.api.orders import router as orders_router

# 前端 @nora/web 商品数据：详见 app/api/products.py
from app.api.products import router as products_router
from app.config import BASE_DIR, settings
from app.services.log_store import log_store
from app.utils.errors import register_exception_handlers
from app.utils.logging import (
    bind_context,
    clear_context,
    configure_logging,
    log_event,
    measure_ms,
)
from app.utils.rate_limit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭：初始化日志、SQLite；关闭时刷队列。"""
    configure_logging(
        settings.log_level,
        log_file=settings.log_file or None,
        service_name=settings.app_name,
        version=settings.version,
    )
    errors = settings.security_configuration_errors()
    if errors:
        # 禁止带着不安全的生产配置继续提供服务；详情只写服务端日志。
        log_event("app.security_config_invalid", errors=errors)
        raise RuntimeError("生产环境安全配置无效，请检查服务端日志")

    log_event("app.startup", host=settings.host, port=settings.port)
    # 记录关键启动状态（不输出明文 key，仅 yes/no）
    log_event("app.config_status", admin_enabled=settings.admin_enabled, llm_configured=settings.llm_configured)
    # 启动日志后台 worker
    try:
        await log_store.startup()
        log_event("log_store.start")
    except Exception as exc:  # noqa: BLE001
        log_event("log_store.start_failed", error=str(exc))
    # 重启恢复：把 LogStore 里最近活跃的会话回填到 DialogueManager
    try:
        from app.services.dialogue_manager import dialogue_manager

        restored = 0
        for sid in log_store.list_active_sessions():
            msgs = log_store.get_messages(sid, limit=dialogue_manager._max_messages)
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in msgs
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
            if dialogue_manager.restore_session(sid, history):
                restored += 1
        log_event("dialogue.restore", sessions=restored)
    except Exception as exc:  # noqa: BLE001
        log_event("dialogue.restore_failed", error=str(exc))
    try:
        yield
    finally:
        log_event("app.shutdown")
        try:
            await log_store.shutdown()
        except Exception as exc:  # noqa: BLE001
            log_event("log_store.shutdown_error", error=str(exc))


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan,
)


# 请求级中间件：注入 request_id、记录访问日志
@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    bind_context(request_id=request_id, method=request.method, path=request.url.path)
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        log_event(
            "request.error",
            latency_ms=measure_ms(start),
            error=str(exc),
        )
        clear_context()
        raise
    response.headers["x-request-id"] = request_id
    log_event(
        "request.done",
        status=response.status_code,
        latency_ms=measure_ms(start),
    )
    clear_context()
    return response


# 中间件：先注册的在**内层**。
# 限流放内层、CORS 放外层，这样 429 等响应也能带上跨域头，浏览器才能读到状态码。
app.add_middleware(RateLimitMiddleware)

# 跨域配置（最外层）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    # 当前认证使用 Authorization header，不依赖浏览器 Cookie，因此不开放跨域凭据。
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 统一异常处理
register_exception_handlers(app)

# 注册路由
app.include_router(chat_router)
app.include_router(audio_router)
app.include_router(knowledge_router)
app.include_router(orders_router)
app.include_router(products_router)
app.include_router(admin_router)
# 鉴权路由：登录 / 当前用户 / 登出（HMAC token）
app.include_router(auth_router)


@app.get("/")
async def root() -> str:
    """根路径：健康检查 / 连通性测试。"""
    return "Hello, AI Customer Service"


@app.get("/health")
async def health() -> dict:
    """健康检查接口（轻量）。"""
    return {"status": "ok", "app": settings.app_name, "version": settings.version}


@app.get("/health/deep")
async def health_deep() -> dict:
    """深度健康检查：含 SQLite 可写 + LLM 配置状态。"""
    db_ok = True
    db_error = None
    try:
        log_store.stats()
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_error = str(exc)

    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.app_name,
        "version": settings.version,
        "checks": {
            "sqlite": {"ok": db_ok, "error": db_error},
            "llm_configured": settings.llm_configured,
        },
    }


# 托管前端页面：访问 http://127.0.0.1:8000/ui 即可打开聊天界面
_frontend_dir = BASE_DIR / "frontend"
if _frontend_dir.is_dir():
    app.mount(
        "/ui",
        StaticFiles(directory=str(_frontend_dir), html=True),
        name="frontend",
    )


if __name__ == "__main__":
    # 优雅退出：SIGTERM（容器停止）/ SIGINT（Ctrl+C）→ uvicorn 触发 lifespan shutdown
    # lifespan 已包含 LogStore 排空队列 + DialogueManager 状态写回
    # 在 Docker / K8s 里，tini / dumb-init 会转发信号；裸跑时直接收到
    import signal

    config = uvicorn.Config(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        # graceful_timeout: 等待正在处理的请求最多 N 秒
        timeout_graceful_shutdown=10,
    )
    server = uvicorn.Server(config)

    def _signal_handler(sig, frame):  # noqa: ARG001
        log_event("app.signal", sig=int(sig))
        server.handle_exit(sig=sig, frame=frame)

    # 仅在主线程有意义（reload=False 时主线程可注册）
    if not settings.debug:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, _signal_handler)

    server.run()
