"""HMAC-SHA256 自签 token（stateless，零依赖）。

Token 格式：
    ``<b64url(payload)>.<b64url(signature)>``

其中：
    - payload 为 JSON：``{"user_id": "u1001", "exp": 1736000000, "jti": "<16 字符>"}``
    - signature = ``HMAC-SHA256(secret, b64url(payload))``

设计要点：
    - 失败统一返回 None / 抛 401，不区分"用户不存在"与"token 过期"（防侧信道探测）
    - ``exp`` 单位秒，使用 UNIX 时间戳；验证时与 ``time.time()`` 比对
    - ``jti`` 仅用于将来扩展黑名单（当前不落地）
    - **签名密钥必须显式配置**（``AUTH_SECRET``）；密钥缺失时禁止回退到任何内置常量，
      否则任何读过源码的人都能用公开常量伪造任意用户身份。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.config import settings


def _b64url_encode(raw: bytes) -> str:
    """URL-safe base64 编码，去掉 ``=`` 填充（更紧凑、对 URL 友好）。"""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """URL-safe base64 解码，自动补齐 ``=`` 填充。"""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


class TokenSecretMissing(RuntimeError):
    """签名密钥未配置（``AUTH_SECRET`` 为空）。

    这是**服务端配置错误**，不是客户端错误：必须显式失败，绝不静默回退到
    内置常量（回退等于把签名密钥公开，任何人都能伪造任意用户身份）。
    """


def _secret() -> bytes:
    """获取签名密钥（必须显式配置，无任何兜底）。

    :raises TokenSecretMissing: ``AUTH_SECRET`` 未配置或为空白
    """
    raw = (settings.auth_secret or "").strip()
    if not raw:
        raise TokenSecretMissing(
            "AUTH_SECRET 未配置：无法签发 / 校验 token。"
            '请在 .env 中设置 AUTH_SECRET，生成方式：python -c "import secrets; '
            'print(secrets.token_urlsafe(32))"'
        )
    return raw.encode("utf-8")


def _sign(payload_b64: str) -> str:
    """对 payload 的 base64 字符串做 HMAC-SHA256，返回 hex 签名的 b64url。"""
    sig = hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(sig)


def create_token(user_id: str, ttl_seconds: int | None = None) -> str:
    """为指定 user_id 签发 token。

    :param user_id: 用户 id
    :param ttl_seconds: 有效期（秒）；不传则用 ``settings.auth_token_ttl_seconds``
    :return: 形如 ``<payload>.<signature>`` 的 token 字符串
    """
    if not user_id:
        raise ValueError("user_id 不能为空")
    ttl = ttl_seconds if ttl_seconds is not None else settings.auth_token_ttl_seconds
    now = int(time.time())
    payload = {
        "user_id": str(user_id),
        "iat": now,
        "exp": now + int(ttl),
        "jti": secrets.token_hex(8),  # 16 字符，预留黑名单扩展
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig_b64 = _sign(payload_b64)
    return f"{payload_b64}.{sig_b64}"


def revoke_token(payload: dict[str, Any]) -> bool:
    """撤销已验证 token；撤销记录持久化到 SQLite，直到 token 自然过期。"""
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not isinstance(jti, str) or not isinstance(exp, (int, float)):
        return False
    from app.services.log_store import log_store

    return log_store.revoke_token(jti, float(exp))


def verify_token(token: str) -> dict[str, Any] | None:
    """验证 token 并返回 payload；任何失败均返回 None（不区分原因）。

    :param token: 待验证的 token 字符串
    :return: ``{"user_id", "iat", "exp", "jti"}``；失败返回 None
    """
    if not token or not isinstance(token, str) or "." not in token:
        return None
    parts = token.split(".")
    if len(parts) != 2:
        return None
    payload_b64, sig_b64 = parts
    # 1. 签名比对（恒定时间比较，防时序攻击）
    try:
        expected_sig = _sign(payload_b64)
    except TokenSecretMissing:
        # 密钥缺失属于服务端配置错误：一律判定为无效（拒绝），不 500 也不放行
        return None
    if not hmac.compare_digest(expected_sig, sig_b64):
        return None
    # 2. payload 解码
    try:
        payload: dict[str, Any] = json.loads(_b64url_decode(payload_b64))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    # 3. 过期校验
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    if time.time() >= exp:
        return None
    # 4. 必要字段校验
    if not payload.get("user_id") or not isinstance(payload.get("jti"), str):
        return None
    from app.services.log_store import log_store

    if log_store.is_token_revoked(payload["jti"]):
        return None
    return payload
