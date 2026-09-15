"""知识库（Knowledge Base）。

对 data/faq.json 建立检索索引，对外提供 ``search(query, top_k)``，
返回最相关的 FAQ 及其得分。检索后端由 ``app/services/retriever.py`` 提供。

P2 加固：
    - **检索缓存**：相同 (query, top_k) 在 TTL（默认 300s）内命中缓存，
      跳过实际检索；``reload()`` 时自动清空。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from app.config import settings
from app.services.retriever import build_retriever
from app.utils.data_loader import load_faqs

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 300.0


@dataclass
class FAQHit:
    """一条 FAQ 检索结果。"""

    id: str
    category: str
    question: str
    answer: str
    score: float

    def to_dict(self) -> dict:
        """转为可序列化的字典（供 API 返回）。"""
        return {
            "id": self.id,
            "category": self.category,
            "question": self.question,
            "score": round(self.score, 4),
        }


def _doc_text(faq: dict) -> str:
    """把一条 FAQ 拼成用于建索引的文本。

    问题与关键词权重更高（重复出现），答案作为补充。
    """
    question = str(faq.get("question", ""))
    keywords = " ".join(faq.get("keywords", []) or [])
    answer = str(faq.get("answer", ""))
    # 问题与关键词重复两次以提高权重
    return f"{question} {question} {keywords} {keywords} {answer}"


class KnowledgeBase:
    """FAQ 知识库（内存索引 + 检索缓存）。"""

    def __init__(self, cache_ttl_seconds: float | None = None) -> None:
        self._faqs: list[dict] = []
        self._index: dict[str, dict] = {}
        self._retriever = None
        # 缓存：key = (query, top_k) → (timestamp, [FAQHit])
        self._cache: dict[tuple[str, int], tuple[float, list[FAQHit]]] = {}
        self._cache_ttl = cache_ttl_seconds if cache_ttl_seconds is not None else settings.faq_cache_ttl_seconds
        self._cache_lock = threading.Lock()
        self._cache_hits = 0
        self._cache_misses = 0
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        """加载 FAQ 并构建检索索引（清空缓存）。"""
        self._faqs = load_faqs()
        self._index = {f["id"]: f for f in self._faqs}
        docs = [_doc_text(f) for f in self._faqs]
        ids = [f["id"] for f in self._faqs]
        self._retriever = build_retriever(docs, ids)
        with self._cache_lock:
            self._cache.clear()
        logger.info(
            "知识库就绪：%d 条 FAQ，后端=%s，缓存 TTL=%ss",
            len(self._faqs),
            type(self._retriever).__name__,
            self._cache_ttl,
        )

    def reload(self) -> None:
        """重建索引并清空缓存（修改 faq.json 后调用）。"""
        self._build()

    # ------------------------------------------------------------------
    @property
    def size(self) -> int:
        """FAQ 条数。"""
        return len(self._faqs)

    @property
    def backend(self) -> str:
        """当前检索后端名称（TfidfRetriever / EmbeddingRetriever）。"""
        return type(self._retriever).__name__

    @property
    def cache_stats(self) -> dict:
        """缓存命中统计。"""
        with self._cache_lock:
            return {
                "size": len(self._cache),
                "ttl_seconds": self._cache_ttl,
                "hits": self._cache_hits,
                "misses": self._cache_misses,
            }

    # ------------------------------------------------------------------
    def search(self, query: str, top_k: int | None = None) -> list[FAQHit]:
        """检索最相关的 FAQ（带缓存）。"""
        if not query or not query.strip():
            return []

        k = top_k or settings.faq_top_k
        key = (query.strip(), k)

        # 1. 查缓存
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached and self._cache_ttl > 0 and (now - cached[0]) < self._cache_ttl:
                self._cache_hits += 1
                return list(cached[1])
            self._cache_misses += 1

        # 2. 实际检索
        raw = self._retriever.search(query, top_k=k)
        hits: list[FAQHit] = []
        for doc_id, score in raw:
            faq = self._index.get(doc_id)
            if not faq:
                continue
            hits.append(
                FAQHit(
                    id=faq["id"],
                    category=faq.get("category", ""),
                    question=faq.get("question", ""),
                    answer=faq.get("answer", ""),
                    score=score,
                )
            )

        # 3. 写缓存（带 LRU 淘汰；TTL<=0 视为关闭缓存）
        if self._cache_ttl > 0:
            with self._cache_lock:
                self._cache[key] = (now, list(hits))
                # 超出容量时按插入顺序淘汰（FIFO，最简单；LRU 太重）
                max_size = settings.faq_cache_max_size
                if max_size > 0:
                    while len(self._cache) > max_size:
                        self._cache.pop(next(iter(self._cache)), None)
        return hits

    def search_answer(self, query: str, top_k: int | None = None) -> list[FAQHit]:
        """仅返回得分不低于阈值的结果（用于判断知识库是否命中）。"""
        return [h for h in self.search(query, top_k) if h.score >= settings.faq_min_score]

    def build_context(self, hits: list[FAQHit]) -> str:
        """把检索结果格式化为供 Prompt 使用的上下文文本。"""
        if not hits:
            return "（知识库未检索到相关条目）"
        blocks = [
            f"[{i}] 分类：{h.category}\n问：{h.question}\n答：{h.answer}"
            for i, h in enumerate(hits, start=1)
        ]
        return "\n\n".join(blocks)


# 模块级单例
knowledge_base = KnowledgeBase()
