"""检索后端（Retriever）。

提供两种 FAQ 检索实现，通过 settings.retriever_backend 选择：

    - TfidfRetriever     —— 中文 TF-IDF / 字符 n-gram，纯 Python，零额外依赖（默认）
    - EmbeddingRetriever —— sentence-transformers + FAISS 语义检索（需额外安装）

两者接口一致：``search(query, top_k) -> list[tuple[doc_id, score]]``

关于中文分词：不引入第三方分词库，采用「英文/数字词 + 中文字（含二元组）」
的切分方式。对 FAQ 这种短文本匹配场景，char-bigram 的效果已足够好。
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter

from app.config import settings

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """中英文混合切分：英文/数字按词，中文按单字 + 相邻二元组。

    :param text: 原始文本
    :return: token 列表
    """
    text = (text or "").lower()
    tokens: list[str] = _WORD_RE.findall(text)

    cjk_chars = _CJK_RE.findall(text)
    tokens.extend(cjk_chars)  # 单字
    # 相邻二字组，弥补单字区分度不足
    tokens.extend(cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1))

    return tokens


# ======================================================================
# TF-IDF（轻量，默认）
# ======================================================================
class TfidfRetriever:
    """基于 TF-IDF + 余弦相似度的检索器（纯 Python 实现）。"""

    def __init__(self, docs: list[str], doc_ids: list[str]) -> None:
        if len(docs) != len(doc_ids):
            raise ValueError("docs 与 doc_ids 长度不一致")

        self.doc_ids = doc_ids
        self._doc_tokens = [tokenize(d) for d in docs]
        self._n = len(docs)

        # 文档频率
        self._df: Counter[str] = Counter()
        for toks in self._doc_tokens:
            self._df.update(set(toks))

        # 预计算文档向量与模长
        self._doc_vecs = [self._to_vec(toks) for toks in self._doc_tokens]
        self._doc_norms = [self._norm(v) for v in self._doc_vecs]

    # ---- 内部 ----
    def _idf(self, term: str) -> float:
        return math.log((1 + self._n) / (1 + self._df.get(term, 0))) + 1.0

    def _to_vec(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        tf = Counter(tokens)
        total = len(tokens)
        return {term: (cnt / total) * self._idf(term) for term, cnt in tf.items()}

    @staticmethod
    def _norm(vec: dict[str, float]) -> float:
        return math.sqrt(sum(v * v for v in vec.values())) or 1.0

    # ---- 对外 ----
    def search(self, query: str, top_k: int = 3) -> list[tuple[str, float]]:
        """检索最相关的 top_k 篇文档。

        :return: [(doc_id, score), ...]，按 score 降序；score 为余弦相似度
        """
        q_vec = self._to_vec(tokenize(query))
        if not q_vec:
            return []
        q_norm = self._norm(q_vec)

        scored: list[tuple[str, float]] = []
        for i, d_vec in enumerate(self._doc_vecs):
            # 稀疏点积：遍历较小的一侧
            if len(q_vec) <= len(d_vec):
                dot = sum(w * d_vec.get(t, 0.0) for t, w in q_vec.items())
            else:
                dot = sum(w * q_vec.get(t, 0.0) for t, w in d_vec.items())
            scored.append((self.doc_ids[i], dot / (q_norm * self._doc_norms[i])))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ======================================================================
# Embedding（可选，sentence-transformers + FAISS）
# ======================================================================
class EmbeddingRetriever:
    """基于 sentence-transformers + FAISS 的语义检索器。

    依赖（需自行安装）：
        pip install sentence-transformers faiss-cpu
    """

    def __init__(self, docs: list[str], doc_ids: list[str], model_name: str) -> None:
        # 延迟导入：未安装依赖时不影响其他后端
        import faiss  # type: ignore
        import numpy as np  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore

        self._np = np
        self.doc_ids = doc_ids
        logger.info("加载 embedding 模型: %s", model_name)
        self._model = SentenceTransformer(model_name)

        embeddings = self._model.encode(
            docs, normalize_embeddings=True, convert_to_numpy=True
        ).astype("float32")
        self._index = faiss.IndexFlatIP(embeddings.shape[1])  # 归一化后内积=余弦
        self._index.add(embeddings)

    def search(self, query: str, top_k: int = 3) -> list[tuple[str, float]]:
        """语义检索最相关的 top_k 篇文档。"""
        q = self._model.encode(
            [query], normalize_embeddings=True, convert_to_numpy=True
        ).astype("float32")
        scores, indices = self._index.search(q, top_k)

        results: list[tuple[str, float]] = []
        for idx, score in zip(indices[0], scores[0], strict=False):
            if idx == -1:
                continue
            results.append((self.doc_ids[idx], float(score)))
        return results


# ======================================================================
# 工厂
# ======================================================================
def build_retriever(docs: list[str], doc_ids: list[str]):
    """按配置构建检索器。

    :param docs: 文档文本列表
    :param doc_ids: 与 docs 一一对应的文档 id
    """
    backend = (settings.retriever_backend or "tfidf").strip().lower()

    if backend in ("embedding", "auto"):
        try:
            return EmbeddingRetriever(docs, doc_ids, settings.embedding_model)
        except Exception as exc:  # 依赖缺失 / 模型下载失败
            if backend == "embedding":
                raise
            logger.warning("Embedding 检索不可用（%s），已回退到 TF-IDF 检索", exc)

    return TfidfRetriever(docs, doc_ids)
