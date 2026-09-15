"""知识库检索测试（默认 TF-IDF 后端）。"""

from __future__ import annotations

import pytest

from app.services.knowledge_base import knowledge_base
from app.services.retriever import TfidfRetriever, tokenize
from app.utils.data_loader import load_faqs


def test_tokenize_splits_chinese_and_ascii():
    tokens = tokenize("退款 Order 123")
    assert "退" in tokens and "款" in tokens
    assert "退款" in tokens  # 中文二元组
    assert "order" in tokens and "123" in tokens


def test_knowledge_base_loaded():
    assert knowledge_base.size == len(load_faqs())
    assert knowledge_base.size >= 20
    assert knowledge_base.backend == "TfidfRetriever"


@pytest.mark.parametrize(
    "query, expected_top1",
    [
        ("退款多久到账", "faq_010"),
        ("物流一直不更新怎么办", "faq_006"),
        ("优惠券怎么用", "faq_013"),
        ("七天无理由退货", "faq_008"),
        ("积分怎么获得", "faq_020"),
        ("支持哪些支付方式", "faq_016"),
    ],
)
def test_search_top1_hits_expected(query, expected_top1):
    hits = knowledge_base.search(query, top_k=3)
    assert hits, f"未检索到结果：{query}"
    assert hits[0].id == expected_top1


def test_search_returns_at_most_top_k():
    hits = knowledge_base.search("订单", top_k=2)
    assert len(hits) <= 2
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)  # 降序


def test_search_empty_query_returns_empty():
    assert knowledge_base.search("") == []
    assert knowledge_base.search("   ") == []


def test_search_answer_filters_by_threshold():
    """无关问题得分低于阈值 → 视为未命中知识库。"""
    assert knowledge_base.search_answer("今天天气怎么样") == []
    assert knowledge_base.search_answer("退款多久到账")  # 相关问题应命中


def test_build_context_contains_required_fields():
    hits = knowledge_base.search("退款多久到账", top_k=1)
    context = knowledge_base.build_context(hits)
    assert "分类：" in context and "问：" in context and "答：" in context

    assert knowledge_base.build_context([]) == "（知识库未检索到相关条目）"


def test_hit_to_dict_shape():
    hit = knowledge_base.search("订单", top_k=1)[0]
    payload = hit.to_dict()
    assert set(payload) == {"id", "category", "question", "score"}
    assert isinstance(payload["score"], float)


def test_tfidf_retriever_direct():
    retriever = TfidfRetriever(
        docs=["退款多久到账", "快递什么时候发货"],
        doc_ids=["a", "b"],
    )
    results = retriever.search("退款要多久", top_k=2)
    assert results[0][0] == "a"
    assert 0.0 <= results[0][1] <= 1.0


def test_tfidf_retriever_length_mismatch():
    with pytest.raises(ValueError):
        TfidfRetriever(docs=["a"], doc_ids=["x", "y"])
