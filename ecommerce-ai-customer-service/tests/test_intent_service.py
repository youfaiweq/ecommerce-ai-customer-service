"""意图识别测试。"""

from __future__ import annotations

import asyncio

import pytest

from app.services.intent_service import Intent, IntentService, intent_service


@pytest.mark.parametrize(
    "text, expected",
    [
        ("帮我查下订单状态", Intent.QUERY_ORDER),
        ("订单号 202609030002 帮我看看", Intent.QUERY_ORDER),
        ("我想取消订单", Intent.QUERY_ORDER),
        ("快递什么时候能到", Intent.QUERY_LOGISTICS),
        ("物流一直不更新", Intent.QUERY_LOGISTICS),
        # 「订单 + 发货」并列时按优先级归入「查询物流」（更贴近用户真实诉求）
        ("我的订单怎么还没发货", Intent.QUERY_LOGISTICS),
        ("我要退货", Intent.RETURN_EXCHANGE),
        ("退款多久到账", Intent.RETURN_EXCHANGE),
        ("这个尺码有货吗", Intent.PRODUCT_INQUIRY),
        ("有什么优惠券可以领", Intent.PROMOTION),
        ("满减活动怎么算", Intent.PROMOTION),
        ("我要转人工", Intent.TRANSFER_HUMAN),
        ("我要投诉", Intent.TRANSFER_HUMAN),
    ],
)
def test_detect_by_rules_matches_expected_intent(text, expected):
    result = intent_service.detect_by_rules(text)
    assert result is not None
    assert result.intent is expected
    assert result.method == "rule"
    assert 0.0 < result.confidence <= 0.95


def test_detect_by_rules_returns_none_without_keywords():
    assert intent_service.detect_by_rules("你好呀") is None
    assert intent_service.detect_by_rules("") is None
    assert intent_service.detect_by_rules("   ") is None


def test_transfer_human_wins_when_tied():
    """多意图并列时，按优先级取「转人工」。"""
    text = "订单要转人工"  # 同时命中 query_order 与 transfer_human
    result = intent_service.detect_by_rules(text)
    assert result is not None
    assert result.intent is Intent.TRANSFER_HUMAN


def test_detect_without_llm_falls_back_to_other():
    result = asyncio.run(intent_service.detect("你好呀", use_llm=False))
    assert result.intent is Intent.OTHER
    assert result.method == "none"


def test_detect_uses_llm_fallback(fake_llm):
    """规则未命中时，应调用大模型分类。"""
    fake_llm.intent = "promotion"
    result = asyncio.run(intent_service.detect("在吗", use_llm=True))
    assert result.intent is Intent.PROMOTION
    assert result.method == "llm"
    assert len(fake_llm.calls) == 1


def test_detect_does_not_call_llm_when_rule_hits(fake_llm):
    asyncio.run(intent_service.detect("我要退货", use_llm=True))
    assert fake_llm.calls == []


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("query_order", Intent.QUERY_ORDER),
        ("QUERY_ORDER", Intent.QUERY_ORDER),
        ("查询物流", Intent.QUERY_LOGISTICS),
        ("我认为是 promotion 吧", Intent.PROMOTION),
        ("完全无法判断", None),
        ("", None),
    ],
)
def test_parse_intent(raw, expected):
    assert IntentService._parse_intent(raw) is expected


def test_intent_result_label_and_dict():
    result = intent_service.detect_by_rules("我要转人工")
    assert result.label == "转人工"
    payload = result.to_dict()
    assert payload["intent"] == "transfer_human"
    assert payload["label"] == "转人工"
    assert set(payload) == {"intent", "label", "confidence", "method"}
