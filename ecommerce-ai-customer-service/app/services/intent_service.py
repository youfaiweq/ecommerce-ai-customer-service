"""意图识别（Intent Recognition）。

策略：**规则优先 + 大模型兜底**。

    1. 先用关键词规则快速命中（零成本、可离线），命中即返回；
    2. 规则未命中时，可选调用大模型做分类（settings.intent_use_llm）；
    3. 大模型不可用 / 解析失败时，兜底为 OTHER。

支持的意图见 ``Intent`` 枚举。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from app.config import settings
from app.services.llm_service import LLMError, llm_service

logger = logging.getLogger(__name__)


class Intent(str, Enum):  # noqa: UP042  # 保持 Python 3.10 兼容性
    """支持的意图类型（值用英文代码，便于程序判断）。"""

    QUERY_ORDER = "query_order"
    QUERY_LOGISTICS = "query_logistics"
    RETURN_EXCHANGE = "return_exchange"
    PRODUCT_INQUIRY = "product_inquiry"
    PROMOTION = "promotion"
    TRANSFER_HUMAN = "transfer_human"
    OTHER = "other"


# 中文标签（用于展示与 Prompt）
INTENT_LABELS: dict[Intent, str] = {
    Intent.QUERY_ORDER: "查询订单",
    Intent.QUERY_LOGISTICS: "查询物流",
    Intent.RETURN_EXCHANGE: "退换货",
    Intent.PRODUCT_INQUIRY: "商品咨询",
    Intent.PROMOTION: "优惠活动",
    Intent.TRANSFER_HUMAN: "转人工",
    Intent.OTHER: "其他",
}

# 规则关键词。命中越多越可信；顺序即优先级（多意图并列时取靠前者）
INTENT_KEYWORDS: dict[Intent, list[str]] = {
    Intent.TRANSFER_HUMAN: [
        "转人工", "人工客服", "真人", "找客服", "客服电话", "转接", "投诉", "我要投诉",
    ],
    Intent.QUERY_LOGISTICS: [
        "物流", "快递", "发货", "什么时候到", "几天到", "派送", "运单", "单号", "包裹",
        "到哪了", "签收", "配送",
    ],
    Intent.QUERY_ORDER: [
        "订单", "下单", "买了", "取消订单", "订单号", "待付款", "待发货", "订单状态",
        "修改地址", "我买的东西",
    ],
    Intent.RETURN_EXCHANGE: [
        "退货", "退款", "换货", "退换", "七天无理由", "售后", "退回", "不想要了", "质量问题",
    ],
    Intent.PROMOTION: [
        "优惠券", "优惠", "满减", "秒杀", "活动", "折扣", "促销", "领券", "红包", "打折",
        "积分",
    ],
    Intent.PRODUCT_INQUIRY: [
        "商品", "产品", "这款", "尺码", "颜色", "规格", "材质", "参数", "库存", "有货吗",
        "多少钱", "价格",
    ],
}

# 意图优先级（用于并列时的取舍，数值越小优先级越高）
_PRIORITY_ORDER: list[Intent] = [
    Intent.TRANSFER_HUMAN,
    Intent.QUERY_LOGISTICS,
    Intent.QUERY_ORDER,
    Intent.RETURN_EXCHANGE,
    Intent.PROMOTION,
    Intent.PRODUCT_INQUIRY,
    Intent.OTHER,
]

# 大模型分类用的 system prompt
_CLASSIFY_PROMPT = (
    "你是一个意图分类器。请判断用户消息属于以下哪一类，"
    "只输出对应的英文代码，不要输出任何解释或标点：\n"
    + "\n".join(f"- {i.value} {INTENT_LABELS[i]}" for i in _PRIORITY_ORDER)
)


@dataclass
class IntentResult:
    """意图识别结果。"""

    intent: Intent
    confidence: float
    method: str  # rule / llm / none

    @property
    def label(self) -> str:
        """意图中文名。"""
        return INTENT_LABELS.get(self.intent, "其他")

    def to_dict(self) -> dict:
        return {
            "intent": self.intent.value,
            "label": self.label,
            "confidence": round(self.confidence, 2),
            "method": self.method,
        }


class IntentService:
    """意图识别服务。"""

    def __init__(self) -> None:
        self._keywords = INTENT_KEYWORDS

    # ------------------------------------------------------------------
    def detect_by_rules(self, text: str) -> IntentResult | None:
        """基于关键词规则识别；未命中返回 None。"""
        content = (text or "").strip()
        if not content:
            return None

        best_intent: Intent | None = None
        best_count = 0

        for intent in _PRIORITY_ORDER:
            count = sum(1 for kw in self._keywords.get(intent, []) if kw in content)
            if count > best_count:
                best_count = count
                best_intent = intent

        if best_intent is None:
            return None

        confidence = min(0.6 + 0.1 * (best_count - 1), 0.95)
        return IntentResult(intent=best_intent, confidence=confidence, method="rule")

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_intent(raw: str) -> Intent | None:
        """从大模型输出中解析意图代码。"""
        text = (raw or "").strip().lower()
        # 精确匹配优先
        for intent in Intent:
            if text == intent.value or text == INTENT_LABELS[intent]:
                return intent
        # 包含匹配兜底
        for intent in Intent:
            if intent.value in text or INTENT_LABELS[intent] in text:
                return intent
        return None

    async def detect_by_llm(self, text: str, llm=llm_service) -> IntentResult | None:
        """调用大模型分类；失败返回 None。"""
        try:
            raw = await llm.achat(
                history=[{"role": "user", "content": text}],
                system_prompt=_CLASSIFY_PROMPT,
                temperature=0.0,
                max_tokens=16,
            )
        except LLMError as exc:
            logger.warning("大模型意图分类失败: %s", exc)
            return None

        intent = self._parse_intent(raw)
        if intent is None:
            logger.warning("无法解析大模型意图输出: %r", raw)
            return None
        return IntentResult(intent=intent, confidence=0.7, method="llm")

    # ------------------------------------------------------------------
    async def detect(self, text: str, use_llm: bool | None = None, llm=llm_service) -> IntentResult:
        """识别意图：规则优先，未命中再走大模型兜底。

        :param text: 用户消息
        :param use_llm: 是否允许大模型兜底，默认取 settings.intent_use_llm
        :param llm: 当前会话选定的模型客户端，确保分类与回答使用同一服务商
        """
        result = self.detect_by_rules(text)
        if result is not None:
            return result

        allow_llm = settings.intent_use_llm if use_llm is None else use_llm
        if allow_llm:
            llm_result = await self.detect_by_llm(text, llm=llm)
            if llm_result is not None:
                return llm_result

        return IntentResult(intent=Intent.OTHER, confidence=0.3, method="none")


# 模块级单例
intent_service = IntentService()
