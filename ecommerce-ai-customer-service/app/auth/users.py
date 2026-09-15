"""演示用户存储：从 ``data/users.json`` 加载账号，并用 PBKDF2 校验密码。

数据文件结构（见 ``scripts/gen_demo_users.py``）：
    [{
        "user_id": "u1001",
        "name": "张伟",
        "email": "u1001@demo.nora",
        "salt": "<32 字符 hex>",
        "password_hash": "<64 字符 hex>",
        "iterations": 100000,
        "algorithm": "pbdf2_hmac_sha256",
        "created_at": "2026-09-14 10:00:00"
    }]

安全约定：
    - 密码用 ``hashlib.pbkdf2_hmac("sha256", ...)`，10w 迭代
    - 比对用恒定时间比较，防时序攻击
    - 成功返回脱敏字典（不含 salt / password_hash / iterations）
    - 失败返回 None（不区分"用户不存在"与"密码错误"）
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, settings

USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
_users_lock = threading.Lock()


def _users_path() -> Path:
    """演示用户 JSON 路径（沿用 settings.data_path 解析逻辑）。"""
    p = Path(settings.data_dir)
    base = p if p.is_absolute() else BASE_DIR / p
    return base / "users.json"


@lru_cache(maxsize=1)
def load_users() -> list[dict[str, Any]]:
    """加载全部演示账号（带缓存；测试可调用 ``reload_users()`` 重新加载）。"""
    path = _users_path()
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def reload_users() -> None:
    """清缓存，下次调用重新读取文件。"""
    load_users.cache_clear()


def _verify_password(password: str, salt_hex: str, expected_hash_hex: str, iterations: int) -> bool:
    """PBKDF2-HMAC-SHA256 密码校验（恒定时间比较）。"""
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_hex.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual, expected_hash_hex)


def _sanitize(user: dict[str, Any]) -> dict[str, Any]:
    """脱敏：去掉 salt / password_hash / iterations / algorithm 等敏感字段。"""
    return {
        "user_id": user.get("user_id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "created_at": user.get("created_at"),
    }


def verify_user(user_id: str, password: str) -> dict[str, Any] | None:
    """校验账号密码；成功返回脱敏用户字典，失败返回 None。

    等长不区分用户不存在 vs 密码错误，防侧信道探测。
    """
    if not user_id or not password:
        return None
    user_id = str(user_id)
    target = None
    for u in load_users():
        if str(u.get("user_id", "")) == user_id:
            target = u
            break
    # 即便用户不存在也跑一次校验，防用户枚举
    salt = target.get("salt", "") if target else "0" * 32
    expected = target.get("password_hash", "") if target else "0" * 64
    iterations = int(target.get("iterations", 100000)) if target else 100000
    if not _verify_password(password, salt, expected, iterations):
        return None
    if target is None:
        return None
    return _sanitize(target)


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    """按 user_id 查找脱敏用户信息（不校验密码）。"""
    if not user_id:
        return None
    user_id = str(user_id)
    for u in load_users():
        if str(u.get("user_id", "")) == user_id:
            return _sanitize(u)
    return None


def create_user(user_id: str, password: str, name: str, email: str | None = None) -> dict[str, Any]:
    """创建本地用户并原子写入 JSON；账号重复或格式非法时抛 ``ValueError``。"""
    user_id = (user_id or "").strip()
    name = (name or "").strip()
    email = (email or "").strip()
    if not USER_ID_PATTERN.fullmatch(user_id):
        raise ValueError("账号仅支持 3-32 位字母、数字、下划线或连字符")
    if not 8 <= len(password or "") <= 128:
        raise ValueError("密码长度必须为 8-128 位")
    if not 1 <= len(name) <= 64:
        raise ValueError("昵称长度必须为 1-64 位")
    if len(email) > 254:
        raise ValueError("邮箱长度不能超过 254 位")

    path = _users_path()
    with _users_lock:
        users = list(load_users())
        if any(str(item.get("user_id", "")).lower() == user_id.lower() for item in users):
            raise ValueError("该账号已被注册")

        salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
        ).hex()
        user = {
            "user_id": user_id,
            "name": name,
            "email": email or None,
            "salt": salt,
            "password_hash": password_hash,
            "iterations": 100_000,
            "algorithm": "pbkdf2_hmac_sha256",
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        users.append(user)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f".tmp-{secrets.token_hex(8)}")
        try:
            temp_path.write_text(json.dumps(users, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        reload_users()
    return _sanitize(user)
