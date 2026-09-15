"""统一错误处理。

把 FastAPI 默认的错误响应统一成如下结构，便于前端与调用方稳定解析：

    {
      "error": {
        "code": "http_404",
        "message": "未找到会话日志：xxx",
        "detail": [...]        # 可选，参数校验错误时给出明细
      }
    }

覆盖三类异常：
    - HTTPException（含 404 / 401 / 429 等）
    - RequestValidationError（请求参数校验失败 → 422）
    - 未捕获异常（→ 500，同时记录完整堆栈到日志）
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def error_body(code: str, message: str, detail=None) -> dict:
    """构造统一错误响应体。"""
    error: dict = {"code": code, "message": message}
    if detail is not None:
        error["detail"] = detail
    return {"error": error}


def _clean_validation_errors(raw: list) -> list[dict]:
    """把 pydantic 的校验错误裁剪为可 JSON 序列化的精简结构。"""
    cleaned = []
    for item in raw or []:
        try:
            cleaned.append(
                {
                    "loc": list(item.get("loc", [])),
                    "msg": str(item.get("msg", "")),
                    "type": str(item.get("type", "")),
                }
            )
        except Exception:  # 极端情况下兜底
            cleaned.append({"msg": str(item)})
    return cleaned


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """处理 HTTPException（404 / 401 / 429 …）。

        若 ``detail`` 是 ``{"code": "...", "message": "..."}`` 形式，则保留自定义 code；
        否则 fallback 到 ``http_<status>`` + 字符串 detail。
        """
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            body = error_body(str(detail["code"]), str(detail["message"]))
            # 若 detail 含其它字段（如 order_no），一并透传
            for k, v in detail.items():
                if k not in ("code", "message") and v is not None:
                    body["error"][k] = v
        else:
            body = error_body(f"http_{exc.status_code}", str(detail))
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """处理请求参数校验失败。"""
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "请求参数校验失败",
                _clean_validation_errors(exc.errors()),
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """兜底：未捕获异常统一返回 500，并记录堆栈。"""
        logger.exception("未处理异常 %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "服务器内部错误，请稍后重试"),
        )
