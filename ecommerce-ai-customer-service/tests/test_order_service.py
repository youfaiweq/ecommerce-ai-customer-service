"""订单 / 物流查询测试。"""

from __future__ import annotations

import pytest

from app.services import order_service
from app.services.order_service import (
    extract_order_no,
    format_order,
    format_tracking,
    list_order_nos,
    lookup,
    normalize_digits,
    resolve_order,
)


# ----------------------------------------------------------------------
# 订单号提取
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("查一下我的订单 123456", "123456"),
        ("订单号 202609030002 帮我看看", "202609030002"),
        ("订单 2026-0901-0001 到哪了", "202609010001"),
        ("订单 2026 0901 0001", "202609010001"),
        ("我的订单怎么还没发货", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_order_no(text, expected):
    assert extract_order_no(text) == expected


def test_extract_order_no_excludes_phone_number():
    """11 位手机号不应被当作订单号。"""
    assert extract_order_no("我的手机号是 13800001234") is None
    # 同时出现手机号与订单号时，取订单号
    assert extract_order_no("手机 13800001234，订单 202609030002") == "202609030002"


def test_extract_prefers_longest_candidate():
    assert extract_order_no("短号 123456 长号 202609030002") == "202609030002"


def test_normalize_digits():
    assert normalize_digits("2026-0901 0001") == "202609010001"
    assert normalize_digits("") == ""


# ----------------------------------------------------------------------
# 订单解析
# ----------------------------------------------------------------------
def test_resolve_order_exact():
    order, matched_by = resolve_order("202609030002")
    assert matched_by == "exact"
    assert order is not None and order["order_no"] == "202609030002"


def test_resolve_order_by_suffix():
    order, matched_by = resolve_order("0002")
    assert matched_by == "suffix"
    assert order is not None and order["order_no"] == "202609030002"


def test_resolve_order_by_contains():
    order, matched_by = resolve_order("123456")
    assert matched_by == "contains"
    assert order is not None and order["order_no"] == "202612345678"


def test_resolve_order_not_found():
    order, matched_by = resolve_order("999999999999")
    assert order is None and matched_by == "none"


def test_resolve_order_too_short_is_not_partial_matched():
    order, matched_by = resolve_order("12")
    assert order is None and matched_by == "none"


# ----------------------------------------------------------------------
# 格式化
# ----------------------------------------------------------------------
def test_format_order_contains_key_info():
    order = lookup(order_no="0002")["order"]
    text = format_order(order)
    assert "订单号：202609030002" in text
    assert "订单状态：运输中" in text
    assert "￥1299.00" in text  # 金额保留两位小数
    assert "商品明细" in text
    assert "物流公司" in text


def test_format_tracking_when_no_logistics():
    order = lookup(order_no="0003")["order"]  # 待发货，无物流
    assert "暂无" in format_tracking(order)


def test_format_tracking_includes_recent_traces():
    order = lookup(order_no="0001")["order"]  # 已签收，含 4 条轨迹
    text = format_tracking(order)
    assert "顺丰速运" in text
    assert "最新轨迹" in text


def test_format_order_includes_refund_info():
    order = lookup(order_no="0005")["order"]  # 退款中
    text = format_order(order)
    assert "退款进度" in text


def test_format_order_includes_cancel_reason():
    order = lookup(order_no="0006")["order"]  # 已取消
    assert "取消原因" in format_order(order)


# ----------------------------------------------------------------------
# lookup 主入口
# ----------------------------------------------------------------------
def test_lookup_with_text():
    result = lookup(text="查一下我的订单 123456")
    assert result["found"] is True
    assert result["order_no"] == "202612345678"
    assert result["matched_by"] == "contains"
    assert "订单号：202612345678" in result["context"]


def test_lookup_prefers_explicit_order_no_over_text():
    result = lookup(text="查一下我的订单 123456", order_no="202609030002")
    assert result["order_no"] == "202609030002"


def test_lookup_without_order_number():
    result = lookup(text="我的订单怎么还没发货")
    assert result["found"] is False
    assert result["matched_by"] == "no_number"
    assert result["context"] == ""


def test_lookup_not_found_mentions_available_numbers():
    result = lookup(text="查订单 999999999999")
    assert result["found"] is False
    assert result["order_no"] == "999999999999"
    assert "未找到订单号" in result["context"]
    assert "202609030002" in result["context"]  # 附带可用订单号提示


def test_list_order_nos():
    nos = list_order_nos()
    assert "202609030002" in nos
    assert len(nos) >= 8


def test_order_service_module_exposes_expected_api():
    for name in ["extract_order_no", "resolve_order", "format_order", "lookup", "list_order_nos"]:
        assert hasattr(order_service, name)
