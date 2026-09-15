"""一次性脚本：生成演示账号 data/users.json（PBKDF2 密码哈希）。

运行： python -m scripts.gen_demo_users
或：   python scripts/gen_demo_users.py
"""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

DEMO_USERS = [
    ("u1001", "张伟"),
    ("u1002", "王芳"),
    ("u1003", "李娜"),
    ("u1004", "陈晨"),
]
DEMO_PASSWORD = "demo123456"
ITERATIONS = 100_000


def _hash_password(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_hex.encode("utf-8"),
        ITERATIONS,
    ).hex()


def main() -> None:
    out_path = Path(__file__).resolve().parent.parent / "data" / "users.json"
    users = [
        {
            "user_id": uid,
            "name": name,
            "email": f"{uid}@demo.nora",
            "salt": (salt := secrets.token_hex(16)),
            "password_hash": _hash_password(DEMO_PASSWORD, salt),
            "iterations": ITERATIONS,
            "algorithm": "pbkdf2_hmac_sha256",
            "created_at": "2026-09-14 10:00:00",
        }
        for uid, name in DEMO_USERS
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(users, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入 {out_path}，演示账号 {len(users)} 个，密码统一 {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
