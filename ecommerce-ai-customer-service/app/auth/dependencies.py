"""FastAPI 鉴权依赖：``HTTPBearer`` + ``verify_token``。

依赖用法：
    @router.get(...)
    async def handler(user: dict = Depends(get_current_user)):
        user_id = user["user_id"]   # 已校验的当前用户
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.tokens import verify_token
from app.auth.users import get_user_by_id
from app.config import settings

# auto_error=False 让"未带 Authorization 头"也能进入依赖（用于可选鉴权场景）
_bearer = HTTPBearer(auto_error=False)


def _resolve_user(credentials: HTTPAuthorizationCredentials | None) -> dict[str, Any] | None:
    """从 Bearer credentials 解析用户；任何失败均返回 None。"""
    if not settings.auth_enabled:
        # 全局关闭鉴权只能用于本地开发/测试；生产环境必须拒绝请求。
        if settings.is_production:
            return None
        return {"user_id": "u1001", "name": "演示", "email": "demo@nora", "created_at": None}
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    payload = verify_token(credentials.credentials)
    if payload is None:
        return None
    user = get_user_by_id(str(payload.get("user_id", "")))
    if user is None:
        return None
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """必鉴权依赖：未带 token / token 无效 / 用户不存在 → 401。"""
    user = _resolve_user(credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "unauthorized",
                "message": "未登录或登录已过期，请重新登录",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any] | None:
    """可选鉴权依赖：未带 token 返回 None；token 无效返回 None（不抛 401）。"""
    return _resolve_user(credentials)
