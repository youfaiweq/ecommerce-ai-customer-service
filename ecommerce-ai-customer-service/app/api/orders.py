"""订单查询路由（只读）。

接口（均需登录）：
    GET /orders              查询当前登录用户的全部订单
    GET /orders/{order_no}   按订单号查询订单（支持后 4-6 位）

鉴权：
    强制依赖 ``get_current_user``；未带 token 或 token 无效 → 401。
    归属校验：仅返回/查看属于当前用户的订单，否则 403（不暴露订单是否存在）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.services import order_service
from app.utils.data_loader import get_orders_by_user

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderQueryResponse(BaseModel):
    """订单查询响应。"""

    found: bool
    order_no: str | None = None
    matched_by: str = Field("none", description="匹配方式：exact/suffix/contains/none")
    order: dict | None = None


class OrderListResponse(BaseModel):
    """订单列表响应。"""

    user_id: str
    count: int
    orders: list[dict] = Field(default_factory=list)


@router.get("", response_model=OrderListResponse, summary="当前登录用户的全部订单")
async def list_orders(
    current_user: dict = Depends(get_current_user),
) -> OrderListResponse:
    """查询当前登录用户的全部订单。"""
    user_id = current_user["user_id"]
    orders = get_orders_by_user(user_id)
    return OrderListResponse(user_id=user_id, count=len(orders), orders=orders)


@router.get("/{order_no}", response_model=OrderQueryResponse, summary="按订单号查询订单")
async def get_order(
    order_no: str,
    current_user: dict = Depends(get_current_user),
) -> OrderQueryResponse:
    """按订单号查询订单；支持只给后 4-6 位（如 ``0002``）。

    归属校验（防越权）：
        仅返回属于当前登录用户的订单；若订单不属于该用户，返回 403，
        且不泄露订单是否存在。
    """
    user_id = current_user["user_id"]
    result = order_service.lookup(order_no=order_no)
    order = result.get("order")
    # 命中订单时做归属校验；不匹配直接 403（不暴露订单是否存在）
    if order and str(order.get("user_id", "")) != str(user_id):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "order_forbidden",
                "message": "无权查看该订单：订单归属与当前用户不一致",
            },
        )
    if result["matched_by"] == "none" and result["order_no"]:
        # 不回显真实订单号：否则任意已登录用户都可借此枚举全量订单。
        raise HTTPException(
            status_code=404,
            detail={
                "code": "order_not_found",
                "message": "未找到该订单，请核对订单号后重试",
            },
        )
    return OrderQueryResponse(
        found=result["found"],
        order_no=result["order_no"],
        matched_by=result["matched_by"],
        order=result["order"],
    )
