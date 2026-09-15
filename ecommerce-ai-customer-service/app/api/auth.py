"""鉴权路由：登录 / 当前用户 / 登出（stateless token）。

接口：
    POST   /auth/login    账号密码换取 token
    GET    /auth/me       查看当前登录用户
    POST   /auth/logout   登出（stateless：客户端丢弃 token 即可）

设计说明：
    - Token 由 ``app.auth.tokens.create_token`` 签发，stateless
    - 服务端不保存 session，登出接口仅为前端语义清晰，返回 204
    - 演示账号见 ``data/users.json``（u1001/u1002/u1003，密码 demo123456）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.auth import create_user, get_current_user, verify_user
from app.auth.tokens import create_token, revoke_token, verify_token
from app.config import settings
from app.utils.logging import log_event

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer()


class LoginRequest(BaseModel):
    """登录请求体。"""

    user_id: str = Field(..., min_length=1, description="用户 id，如 u1001")
    password: str = Field(..., min_length=1, description="密码")


class RegisterRequest(BaseModel):
    """本地个人部署的注册请求。"""

    user_id: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=254)


class UserResponse(BaseModel):
    """脱敏用户信息。"""

    user_id: str
    name: str | None = None
    email: str | None = None
    created_at: str | None = None


class LoginResponse(BaseModel):
    """登录成功响应。"""

    token: str
    token_type: str = "Bearer"
    expires_in: int = Field(..., description="token 有效期（秒）")
    user: UserResponse


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="账号密码登录换取 token",
)
async def login(payload: LoginRequest) -> LoginResponse:
    """演示账号登录：校验 ``user_id`` + ``password``，成功返回 HMAC token。"""
    user = verify_user(payload.user_id, payload.password)
    if user is None:
        # 不区分"用户不存在"与"密码错误"
        log_event("auth.login_failed", user_id=payload.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_credentials",
                "message": "账号或密码错误",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_token(user["user_id"])
    log_event("auth.login_ok", user_id=user["user_id"])
    return LoginResponse(
        token=token,
        expires_in=settings.auth_token_ttl_seconds,
        user=UserResponse(
            user_id=user["user_id"],
            name=user.get("name"),
            email=user.get("email"),
            created_at=user.get("created_at"),
        ),
    )


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest) -> LoginResponse:
    """创建账户并直接签发登录 token。"""
    try:
        user = create_user(payload.user_id, payload.password, payload.name, payload.email)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "registration_invalid", "message": str(exc)},
        ) from exc
    token = create_token(user["user_id"])
    log_event("auth.register_ok", user_id=user["user_id"])
    return LoginResponse(
        token=token,
        expires_in=settings.auth_token_ttl_seconds,
        user=UserResponse(**user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="查看当前登录用户",
)
async def me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    """凭 token 查看当前登录用户信息。"""
    return UserResponse(
        user_id=current_user["user_id"],
        name=current_user.get("name"),
        email=current_user.get("email"),
        created_at=current_user.get("created_at"),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="登出（客户端丢弃 token）",
)
async def logout(
    _: dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> None:
    """撤销当前 token，使其在到期前立即失效。"""
    payload = verify_token(credentials.credentials)
    if payload is None or not revoke_token(payload):
        raise HTTPException(
            status_code=503,
            detail={"code": "logout_unavailable", "message": "登出服务暂时不可用，请稍后重试"},
        )
    return None
