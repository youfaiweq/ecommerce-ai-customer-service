"""订单 / 物流查询服务。

职责：
    - 从用户消息中提取订单号（``extract_order_no``）
    - 到 data/orders.json 中解析订单（``resolve_order``：精确 → 后缀 → 包含）
    - 把订单 / 物流信息格式化为适合放入 Prompt 的自然语言文本

数据来源为 ``app/utils/data_loader.py``（带缓存），修改 JSON 后调用
``data_loader.reload_data()`` 即可生效。
"""

from __future__ import annotations

import logging
import re

from app.utils.data_loader import get_order_by_no, load_orders

logger = logging.getLogger(__name__)

# 订单号候选：6 位以上数字，允许中间夹空格或短横线（如 2026-0901-0001）
_CANDIDATE_RE = re.compile(r"\d(?:[\s\-]?\d){5,}")
# 手机号（11 位，1 开头），不应被误当作订单号
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

# 后缀 / 包含匹配的最小长度，避免过短数字乱匹配
_MIN_PARTIAL_LEN = 4


def normalize_digits(text: str) -> str:
    """去掉数字串中的空格 / 短横线。"""
    return re.sub(r"[\s\-]", "", text or "")


def _fmt_amount(value) -> str:
    """金额格式化为两位小数；无法解析时原样返回。"""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def extract_order_no(text: str) -> str | None:
    """从文本中提取订单号。

    规则：匹配 6 位及以上数字（允许分隔符），排除手机号；
    多个候选时取最长的一个。

    :param text: 用户消息
    :return: 归一化后的订单号，未找到返回 None
    """
    if not text:
        return None

    candidates: list[str] = []
    for match in _CANDIDATE_RE.finditer(text):
        digits = normalize_digits(match.group())
        if _PHONE_RE.match(digits):  # 排除手机号
            continue
        candidates.append(digits)

    if not candidates:
        return None

    candidates.sort(key=len, reverse=True)
    return candidates[0]


def resolve_order(order_no: str) -> tuple[dict | None, str]:
    """按订单号解析订单。

    依次尝试：精确匹配 → 后缀匹配 → 包含匹配。

    :param order_no: 订单号（可只给后几位）
    :return: (订单字典 或 None, 匹配方式: exact / suffix / contains / none)
    """
    if not order_no:
        return None, "none"

    target = normalize_digits(order_no)

    # 1. 精确匹配
    order = get_order_by_no(target)
    if order:
        return order, "exact"

    if len(target) < _MIN_PARTIAL_LEN:
        return None, "none"

    # 2. 后缀匹配（用户常只报后 4-6 位）
    suffix_matches = [o for o in load_orders() if o["order_no"].endswith(target)]
    if len(suffix_matches) == 1:
        return suffix_matches[0], "suffix"

    # 3. 包含匹配
    contains_matches = [o for o in load_orders() if target in o["order_no"]]
    if len(contains_matches) == 1:
        return contains_matches[0], "contains"

    return None, "none"


# ----------------------------------------------------------------------
# 格式化
# ----------------------------------------------------------------------
def format_tracking(order: dict) -> str:
    """把订单的物流信息格式化为文本。"""
    logistics = order.get("logistics")
    if not logistics:
        return "物流信息：暂无（该订单尚未发货）"

    lines = [
        f"物流公司：{logistics.get('company', '-')}",
        f"运单号：{logistics.get('tracking_no', '-')}",
        f"物流状态：{logistics.get('status', '-')}",
    ]
    traces = logistics.get("traces") or []
    if traces:
        lines.append("最新轨迹：")
        for trace in traces[-3:]:  # 只取最近 3 条，控制长度
            lines.append(f"  · {trace.get('time', '')} {trace.get('desc', '')}")
    return "\n".join(lines)


def format_order(order: dict, include_logistics: bool = True) -> str:
    """把订单信息格式化为自然语言文本（供 Prompt 使用）。"""
    lines = [
        f"订单号：{order.get('order_no', '-')}",
        f"订单状态：{order.get('status', '-')}",
        f"下单时间：{order.get('created_at', '-')}",
        f"实付金额：￥{_fmt_amount(order.get('total_amount'))}",
    ]

    products = order.get("products") or []
    if products:
        items = "；".join(
            f"{p.get('name', '')} ×{p.get('quantity', 1)}" for p in products
        )
        lines.append(f"商品明细：{items}")

    if order.get("paid_at"):
        lines.append(f"支付时间：{order['paid_at']}")
    if order.get("shipped_at"):
        lines.append(f"发货时间：{order['shipped_at']}")

    if include_logistics:
        lines.append(format_tracking(order))

    refund = order.get("refund")
    if refund:
        lines.append(
            f"退款进度：{refund.get('status', '-')}（原因：{refund.get('reason', '-')}，"
            f"金额：￥{_fmt_amount(refund.get('amount'))}）"
        )
    if order.get("cancel_reason"):
        lines.append(f"取消原因：{order['cancel_reason']}")

    return "\n".join(lines)


def list_order_nos() -> list[str]:
    """列出全部订单号（用于「未找到订单」时给用户提示）。"""
    return [o["order_no"] for o in load_orders()]


# ----------------------------------------------------------------------
# 对外主入口
# ----------------------------------------------------------------------
def lookup(text: str | None = None, order_no: str | None = None) -> dict:
    """查询订单：优先使用显式 order_no（槽位），否则从文本中提取。

    :param text: 用户消息
    :param order_no: 已知订单号（来自会话槽位）
    :return: 结构化结果：
        {
            "found": bool,
            "order_no": str | None,
            "matched_by": str,       # exact / suffix / contains / none / no_number
            "context": str,          # 供 Prompt 使用的文本
            "order": dict | None,
        }
    """
    candidate = order_no or extract_order_no(text or "")

    if not candidate:
        return {
            "found": False,
            "order_no": None,
            "matched_by": "no_number",
            "context": "",
            "order": None,
        }

    order, matched_by = resolve_order(candidate)
    if not order:
        return {
            "found": False,
            "order_no": candidate,
            "matched_by": "none",
            "context": (
                f"未找到订单号「{candidate}」对应的订单。\n"
                f"（演示可用的订单号：{'、'.join(list_order_nos())}，"
                f"也可只提供订单号后 4-6 位）"
            ),
            "order": None,
        }

    return {
        "found": True,
        "order_no": order["order_no"],
        "matched_by": matched_by,
        "context": format_order(order),
        "order": order,
    }
