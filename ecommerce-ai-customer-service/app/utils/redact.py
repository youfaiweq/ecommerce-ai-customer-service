"""PII（个人敏感信息）脱敏工具。

统一的脱敏入口，供结构化日志、LogStore、聊天历史持久化等共用。
策略：

- 手机号（中国大陆 11 位）：保留前 3 后 4，中间 4 位替换为 `*`
- 邮箱：用户名第 2 位起替换为 `*`，保留首字母与域名
- 身份证（18 位 / 15 位）：保留前 4 后 4
- 银行卡（12~19 位数字）：保留后 4
- 订单号（≥ 6 位数字）：保留前 4 后 2，长度不足时整体替换
- 用户输入里的纯 IP（IPv4）：末段替换

策略既可整体替换也可保留部分特征，便于事后追溯又不暴露完整隐私。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# 中国大陆手机号
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 邮箱（宽松匹配，含 .com / .cn 等）
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 身份证（18 位含 X / 15 位）
_IDCARD_RE = re.compile(r"(?<!\d)[1-9]\d{13,16}[\dXx](?!\d)")
# 银行卡（12~19 位连续数字，按卡号常见长度）
_BANKCARD_RE = re.compile(r"(?<!\d)\d{12,19}(?!\d)")
# 订单号：≥ 6 位连续数字（订单场景里通常是 6+ 位）
# 排除手机号 / 身份证已经被前置规则吃掉的部分
_ORDERNO_RE = re.compile(r"(?<!\d)\d{6,}(?!\d)")
# IPv4
_IPV4_RE = re.compile(r"(?<!\d)(\d{1,3}\.){3}\d{1,3}(?!\d)")

# 提示词注入 / 越权模式（用于 chat_service 的硬拦截）
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"忽略(以上|上述|之前|上文|前面)(的|所有)?(指令|提示|规则|设定)", re.IGNORECASE),
    re.compile(r"you\s+are\s+(now\s+)?(a\s+)?", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\s*/?\s*(system|assistant|user|tool)\s*>", re.IGNORECASE),
    re.compile(r"prompt\s*:\s*", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?(system|hidden|secret)", re.IGNORECASE),
    re.compile(r"打印(出|一下)?(你的)?(系统|隐藏|原始|初始)?(提示|prompt|指令)"),
)


def redact_phone(text: str) -> str:
    """手机号：保留前 3 后 4，中间 4 位变 `*`。"""
    return _PHONE_RE.sub(lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:], text)


def redact_email(text: str) -> str:
    """邮箱：保留用户名首字母与域名，中间变 `*`。"""
    def _sub(m: re.Match[str]) -> str:
        local, domain = m.group(0).split("@", 1)
        if len(local) <= 1:
            masked = local + "*"
        else:
            masked = local[0] + "*" * (len(local) - 1)
        return f"{masked}@{domain}"

    return _EMAIL_RE.sub(_sub, text)


def redact_idcard(text: str) -> str:
    """身份证：保留前 4 后 4。"""
    return _IDCARD_RE.sub(lambda m: m.group(0)[:4] + "*" * (len(m.group(0)) - 8) + m.group(0)[-4:], text)


def redact_bankcard(text: str) -> str:
    """银行卡：保留后 4。"""
    return _BANKCARD_RE.sub(lambda m: "*" * (len(m.group(0)) - 4) + m.group(0)[-4:], text)


def redact_orderno(text: str) -> str:
    """订单号：保留前 4 后 2。"""
    def _sub(m: re.Match[str]) -> str:
        s = m.group(0)
        if len(s) <= 6:
            return "*" * len(s)
        return s[:4] + "*" * (len(s) - 6) + s[-2:]

    return _ORDERNO_RE.sub(_sub, text)


def redact_ip(text: str) -> str:
    """IPv4：保留前三段，末段变 `*`。"""
    return _IPV4_RE.sub(lambda m: ".".join(m.group(0).split(".")[:3]) + ".*", text)


def redact_text(text: str, *, phone: bool = True, email: bool = True,
                idcard: bool = True, bankcard: bool = True,
                orderno: bool = True, ip: bool = True) -> str:
    """对一段文本按需脱敏。默认全开。"""
    if not text:
        return text
    if phone:
        text = redact_phone(text)
    if email:
        text = redact_email(text)
    if idcard:
        text = redact_idcard(text)
    if bankcard:
        text = redact_bankcard(text)
    if orderno:
        text = redact_orderno(text)
    if ip:
        text = redact_ip(text)
    return text


def redact_dict(data: dict[str, Any] | None, *, keys: Iterable[str] = (),
                recursive: bool = True) -> dict[str, Any]:
    """对 dict 中的指定 key 递归脱敏；未指定 key 时按字段名启发式识别。"""
    if not isinstance(data, dict):
        return data or {}

    sensitive_keys = {
        "message", "user_message", "content", "reply", "text", "question",
        "order_no", "phone", "mobile", "email", "idcard", "id_card",
        "bank_card", "bankcard", "address", "name", "real_name",
        "ip", "client_ip", "remote_addr",
    }
    keys_set = set(keys) if keys else None

    out: dict[str, Any] = {}
    for k, v in data.items():
        should = (keys_set and k in keys_set) or (
            not keys_set and isinstance(k, str) and k.lower() in sensitive_keys
        )
        if should and isinstance(v, str):
            out[k] = redact_text(v)
        elif recursive and isinstance(v, dict):
            out[k] = redact_dict(v, keys=keys, recursive=True)
        elif recursive and isinstance(v, list):
            out[k] = [
                redact_dict(x, keys=keys, recursive=True) if isinstance(x, dict)
                else redact_text(x) if isinstance(x, str) and should
                else x
                for x in v
            ]
        else:
            out[k] = v
    return out


def detect_injection(text: str) -> bool:
    """检测用户输入是否包含典型的 prompt 注入 / 越权模式。"""
    if not text:
        return False
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            return True
    return False


def safe_log_value(value: Any, *, max_len: int = 2000) -> Any:
    """脱敏 + 截断，供日志输出。"""
    if isinstance(value, str):
        v = redact_text(value)
        if len(v) > max_len:
            v = v[:max_len] + "..."
        return v
    if isinstance(value, dict):
        return redact_dict(value)
    if isinstance(value, list):
        return [safe_log_value(x, max_len=max_len) for x in value]
    return value


__all__ = [
    "redact_text",
    "redact_dict",
    "redact_phone",
    "redact_email",
    "redact_idcard",
    "redact_bankcard",
    "redact_orderno",
    "redact_ip",
    "detect_injection",
    "safe_log_value",
]
