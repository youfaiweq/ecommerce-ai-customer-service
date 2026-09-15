"""知识库路由（用于检索调试 / 对外暴露 FAQ 检索能力）。

接口：
    GET  /knowledge/search?q=关键词&top_k=3   检索最相关的 FAQ
    GET  /knowledge/stats                     知识库规模 + 索引新鲜度
    POST /knowledge/reload                    强制重建索引（修改 faq.json 后调用）

热更新说明：
    默认**不**自动监听文件改动（避免引入 watchdog 依赖）。
    修改 `data/faq.json` 后调用 `POST /knowledge/reload` 即可生效。
    若需要自动监听，建议在外部脚本里用 `inotifywait` / `fswatch` 监听后
    curl 调用本接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.admin import require_admin_key
from app.config import settings
from app.services.knowledge_base import knowledge_base
from app.utils.data_loader import load_faqs
from app.utils.logging import log_event

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class FAQSearchResponse(BaseModel):
    """FAQ 检索响应。"""

    query: str
    count: int
    backend: str
    top_k: int
    hits: list[dict] = Field(default_factory=list)


class KnowledgeReloadResponse(BaseModel):
    """知识库重建结果。"""

    reloaded: bool
    faq_count: int
    backend: str
    previous_count: int


@router.get("/search", response_model=FAQSearchResponse, summary="检索 FAQ 知识库")
async def search_faq(
    q: str = Query(..., min_length=1, description="查询关键词"),
    top_k: int | None = Query(default=None, ge=1, le=20, description="返回条数"),
) -> FAQSearchResponse:
    """检索知识库，返回最相关的 FAQ（含相关度得分与完整答案）。"""
    k = top_k or settings.faq_top_k
    hits = knowledge_base.search(q, top_k=k)

    return FAQSearchResponse(
        query=q,
        count=len(hits),
        backend=knowledge_base.backend,
        top_k=k,
        hits=[
            {**h.to_dict(), "answer": h.answer, "matched": h.score >= settings.faq_min_score}
            for h in hits
        ],
    )


@router.get("/stats", summary="知识库概览")
async def stats() -> dict:
    """返回知识库规模、检索后端、文件新鲜度。"""
    faq_path = settings.data_path / "faq.json"
    info = {
        "faq_count": knowledge_base.size,
        "backend": knowledge_base.backend,
        "top_k": settings.faq_top_k,
        "min_score": settings.faq_min_score,
        "faq_path": str(faq_path),
        "faq_exists": faq_path.exists(),
    }
    if faq_path.exists():
        info["faq_mtime"] = faq_path.stat().st_mtime
        info["faq_size_bytes"] = faq_path.stat().st_size
    return info


@router.post(
    "/reload",
    response_model=KnowledgeReloadResponse,
    summary="强制重建 FAQ 索引",
)
async def reload_knowledge(
    _: None = Depends(require_admin_key),
) -> KnowledgeReloadResponse:
    """重建知识库索引（修改 faq.json 后调用）。

    流程：
        1. 校验 faq.json 格式（重新加载一次）
        2. 重建内存索引
        3. 返回新/旧条数 + 后端类型
    """
    # 先尝试加载一次，校验格式
    try:
        load_faqs()  # noqa: F841
    except Exception as exc:  # noqa: BLE001
        log_event("knowledge.reload_failed", error=str(exc))
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"faq.json 加载失败：{exc}",
        ) from exc

    previous = knowledge_base.size
    # 先清掉 lru_cache，确保拿到最新的 faq.json 内容
    from app.utils.data_loader import reload_data

    reload_data()
    knowledge_base.reload()
    log_event(
        "knowledge.reload",
        previous=previous,
        current=knowledge_base.size,
        backend=knowledge_base.backend,
    )
    return KnowledgeReloadResponse(
        reloaded=True,
        faq_count=knowledge_base.size,
        backend=knowledge_base.backend,
        previous_count=previous,
    )
