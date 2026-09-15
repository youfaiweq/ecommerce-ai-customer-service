"""商品 API —— 提供给前端 @nora/web 列表 / 详情 / 搜索。

数据来源：
    data/products.json  （与前端 mock data 同时维护，可日后做 SSG / CMS）

设计：
    * 单例加载，启动后驻内存；商品数据小（< 100 条），性能不是瓶颈
    * 错误用统一的 JSONResponse 形态（与现有 orders API 一致）
    * 暂时不做分页（产品列表 < 50 条），日后扩展加分页 + tag 过滤
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.models.product import ProductListResponse, ProductModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["products"])


# 单例加载：模块级缓存，刷新通过重启服务
_CACHE: list[dict] | None = None


def _load_products() -> list[dict]:
    """从 data/products.json 加载并缓存。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = Path(__file__).resolve().parent.parent.parent / "data" / "products.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("products.json must be a JSON array")
        _CACHE = data
        logger.info("products.loaded count=%s", len(_CACHE))
        return _CACHE
    except FileNotFoundError:
        logger.error("products.missing path=%s", path)
        return []
    except Exception as exc:
        logger.exception("products.load_failed: %s", exc)
        return []


@router.get("", response_model=ProductListResponse)
@router.get("/", response_model=ProductListResponse)
async def list_products(
    cat: str | None = Query(None, description="headphones / watches / speakers / accessories / all"),
    category: str | None = Query(None, description="alias for cat"),
    q: str | None = Query(None, description="简易关键字搜索（匹配 name / sku / tagline）"),
    in_stock_only: bool = Query(False, description="只返回现货"),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """返回全部（或按 category / q / 库存过滤）商品。"""
    effective = (cat or category or "all").lower()
    items = _load_products()
    if effective != "all":
        items = [p for p in items if p.get("category") == effective]
    if q:
        q_lower = q.lower()
        items = [
            p
            for p in items
            if q_lower in p.get("name", "").lower()
            or q_lower in p.get("sku", "").lower()
            or q_lower in p.get("tagline", "").lower()
        ]
    if in_stock_only:
        items = [p for p in items if p.get("stock") == "in_stock"]
    items = items[:limit]
    return {
        "items": items,
        "total": len(items),
        "categories": _list_categories(),
    }


@router.get("/{product_id}", response_model=ProductModel)
async def get_product(product_id: str):
    """返回单个商品详情。"""
    for p in _load_products():
        if p.get("id") == product_id:
            return p
    raise HTTPException(
        status_code=404,
        detail={"code": "product_not_found", "message": f"未找到商品 {product_id}"},
    )


def _list_categories() -> list[dict]:
    """返回现有商品覆盖的类目统计。"""
    items = _load_products()
    seen: dict[str, int] = {}
    for p in items:
        c = p.get("category", "unknown")
        seen[c] = seen.get(c, 0) + 1
    return [{"key": k, "count": v} for k, v in sorted(seen.items())]
