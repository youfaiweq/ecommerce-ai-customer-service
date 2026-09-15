"""HMAC token 单元测试：生成、验证、过期、篡改。"""

from __future__ import annotations

import time

from app.auth.tokens import create_token, verify_token


def test_create_and_verify_token_round_trip():
    """正常路径：签发 → 验证 → 拿回 user_id。"""
    token = create_token("u1001")
    assert isinstance(token, str) and "." in token
    payload = verify_token(token)
    assert payload is not None
    assert payload["user_id"] == "u1001"
    assert "exp" in payload and "iat" in payload and "jti" in payload


def test_verify_token_rejects_garbage():
    """各种坏 token 都应返回 None，不抛异常。"""
    for bad in ["", "abc", "abc.def.ghi", "x.y", None, "  "]:  # noqa: B008
        assert verify_token(bad) is None  # type: ignore[arg-type]


def test_verify_token_tampered_payload():
    """篡改 payload 应导致签名校验失败。"""
    token = create_token("u1001")
    payload_part, _sig = token.split(".", 1)
    # 把 payload 第一个字符换成不同的字符
    flipped = "a" if payload_part[0] != "a" else "b"
    tampered_payload = flipped + payload_part[1:]
    tampered = f"{tampered_payload}.{token.split('.', 1)[1]}"
    assert verify_token(tampered) is None


def test_verify_token_tampered_signature():
    """篡改 signature 应失败。"""
    token = create_token("u1001")
    payload_part, sig_part = token.split(".", 1)
    flipped = "a" if sig_part[0] != "a" else "b"
    tampered = f"{payload_part}.{flipped + sig_part[1:]}"
    assert verify_token(tampered) is None


def test_verify_token_expired():
    """过期 token 应返回 None。"""
    # ttl=0 → 立即过期
    token = create_token("u1001", ttl_seconds=0)
    # sleep 一点点确保时间过了
    time.sleep(0.01)
    assert verify_token(token) is None


def test_create_token_rejects_empty_user_id():
    """空 user_id 不应签发。"""
    try:
        create_token("")
    except ValueError:
        return
    raise AssertionError("空 user_id 应抛 ValueError")
