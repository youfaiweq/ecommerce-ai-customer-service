"""结构化 JSON 日志。

设计目标：
- 一行一个 JSON 对象，方便 Docker / K8s / Filebeat / Loki 直接收集
- 自带 PII 脱敏，避免把手机号 / 邮箱 / 订单号泄漏到日志聚合系统
- 通过 contextvars 携带 request_id / session_id / intent 等上下文，无需每个日志显式传参
- 默认走 stdout（容器友好），文件路径可选

用法：

    from app.utils.logging import configure_logging, bind_context, log_event

    configure_logging("INFO")
    bind_context(request_id="...", session_id="...")

    log_event("chat.llm_call", model="gpt-4o-mini", latency_ms=812)
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from logging import LogRecord
from pathlib import Path
from typing import Any

from app.utils.redact import redact_text, safe_log_value

# 上下文变量：跨调用栈共享（async 安全）
_context_vars: dict[str, ContextVar[Any]] = {}


def _cv(name: str) -> ContextVar[Any]:
    if name not in _context_vars:
        _context_vars[name] = ContextVar(name, default=None)
    return _context_vars[name]


def bind_context(**kwargs: Any) -> None:
    """把上下文写入 ContextVar，供后续日志自动带上。"""
    for k, v in kwargs.items():
        if v is None:
            continue
        var = _cv(k)
        var.set(v)


def clear_context() -> None:
    for var in _context_vars.values():
        var.set(None)


def _ctx_snapshot() -> dict[str, Any]:
    return {k: v.get() for k, v in _context_vars.items() if v.get() is not None}


class JsonFormatter(logging.Formatter):
    """JSON 日志格式器：含时间、级别、消息、上下文、异常、自动脱敏。"""

    def __init__(self, *, redact: bool = True, extra_static: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.redact = redact
        self.extra_static = extra_static or {}

    def format(self, record: LogRecord) -> str:
        # 先格式化消息（处理 %s / %d 占位符），再做脱敏
        try:
            msg_text = record.getMessage()
        except Exception:
            msg_text = str(record.msg)
        # 消息文本默认就是 PII 敏感字段（用户消息、SQL 参数等都会进 msg）
        if self.redact:
            msg_text = redact_text(msg_text)
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": msg_text,
        }
        # 上下文
        ctx = _ctx_snapshot()
        if ctx:
            payload["ctx"] = ctx
        # 静态附加（service / env / version）
        if self.extra_static:
            payload["meta"] = self.extra_static
        # 业务自定义字段（logger.info("x", extra={...})）
        for k, v in record.__dict__.items():
            if k in {
                "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "message", "asctime", "taskName",
            }:
                continue
            payload[k] = v
        # 异常
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # 脱敏
        if self.redact:
            payload = safe_log_value(payload)
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            # 兜底：把非序列化字段转字符串
            fallback = {k: str(v) for k, v in payload.items()}
            return json.dumps(fallback, ensure_ascii=False)


def configure_logging(
    level: str = "INFO",
    *,
    log_file: str | Path | None = None,
    service_name: str = "ecommerce-ai-customer-service",
    version: str = "",
    redact: bool = True,
) -> None:
    """初始化全局日志：JSON 输出到 stdout，可选再写一份到文件。"""
    formatter = JsonFormatter(
        redact=redact,
        extra_static={"service": service_name, "version": version} if version else {"service": service_name},
    )

    root = logging.getLogger()
    # 清掉已有的 handlers（reload-safe）
    for h in list(root.handlers):
        root.removeHandler(h)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # 抑制过吵的第三方
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def log_event(event: str, /, **fields: Any) -> None:
    """业务事件日志：自动绑定 event 名 + 任意字段。

    自动避坑：Python ``logging.LogRecord`` 保留一批内部字段（filename / module /
    msg / args / ...），如果 ``fields`` 撞名会 KeyError。这里把所有保留名
    前缀化（filename → __asr_filename 等），保留下游 JSON 结构稳定可读。
    """
    bind_context(event=event)
    try:
        # 推迟到 _log 里再 import 避免循环
        safe_fields = _sanitize_log_fields(fields)
        logging.getLogger("event").info(event, extra=safe_fields)
    finally:
        _cv("event").set(None)


# Python logging 保留字段（注意：set 在 _logRecord 上，重复 set 即 KeyError）
_LOGRESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


def _sanitize_log_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """把与 LogRecord 保留名冲突的 key 自动前缀化，避免 KeyError('Attempt to overwrite ...')。"""
    out = {}
    for k, v in fields.items():
        if k in _LOGRESERVED:
            out[f"__ctx_{k}"] = v
        else:
            out[k] = v
    return out


def measure_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


__all__ = [
    "configure_logging",
    "bind_context",
    "clear_context",
    "log_event",
    "measure_ms",
    "JsonFormatter",
]
