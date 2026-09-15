"""鉴权包：HMAC-SHA256 自签 token + 演示用户存储 + FastAPI 依赖。

设计目标：
    - 零新依赖：仅用 stdlib（``hmac`` / ``hashlib`` / ``json`` / ``base64`` / ``secrets``）
    - 可演示：``data/users.json`` 预置 3 个账号，密码统一 ``demo123456``
    - 可扩展：生产环境替换 ``users.py`` 为真实用户库、``tokens.py`` 为 JWT 即可

公开接口：
    - ``create_token(user_id)``  生成 token
    - ``verify_token(token)``    验证并返回 payload，失败返回 None
    - ``verify_user(user_id, password)``  校验账号密码，返回脱敏 user 字典
    - ``get_current_user``       FastAPI 依赖：必鉴权
    - ``get_current_user_optional``  FastAPI 依赖：可选鉴权（未带 token 返回 None）
"""
from app.auth.dependencies import get_current_user, get_current_user_optional
from app.auth.tokens import create_token, revoke_token, verify_token
from app.auth.users import create_user, load_users, verify_user

__all__ = [
    "create_token",
    "verify_token",
    "revoke_token",
    "load_users",
    "verify_user",
    "create_user",
    "get_current_user",
    "get_current_user_optional",
]
