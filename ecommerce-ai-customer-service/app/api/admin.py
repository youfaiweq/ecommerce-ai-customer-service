"""管理接口：查看历史会话日志。

接口：
    GET    /admin/sessions                       会话列表（分页）
    GET    /admin/sessions/{session_id}          某会话的完整消息
    GET    /admin/sessions/{session_id}/export   导出单会话（JSON / Markdown）
    GET    /admin/search?q=                      按关键词搜索消息
    GET    /admin/stats                          汇总统计
    DELETE /admin/sessions/{session_id}          删除某会话日志

鉴权：
    - **默认拒绝**：未配置 ``ADMIN_API_KEY`` / ``ADMIN_API_KEYS`` 时，所有管理接口
      一律返回 ``503``（配置缺失），绝不静默放行；
    - 已配置时，请求必须携带 ``X-Admin-Key`` 且命中配置的任一密钥，否则返回 ``401``；
    - 管理密钥独立于业务 token 体系，使用单独的高强度随机值，不与用户 token 混用。
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.services.intent_service import INTENT_LABELS
from app.services.log_store import log_store

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    """管理接口鉴权依赖（**默认拒绝**）。

    - 未配置任何管理密钥 → 503：这是服务端配置缺失，不是客户端无权，
      因此不能静默放行（既便于运维定位，也避免生产误开导致会话数据裸奔）；
    - 已配置 → 必须携带 ``X-Admin-Key`` 且命中 ``settings.admin_keys``，否则 401。
    """
    if not settings.admin_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "admin_key_not_configured",
                "message": (
                    "管理接口未启用：服务端未配置 ADMIN_API_KEY / ADMIN_API_KEYS，"
                    "已按默认拒绝策略拦截全部管理请求。"
                ),
            },
        )
    if not x_admin_key or x_admin_key not in settings.admin_keys:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "admin_key_invalid",
                "message": "管理密钥无效：请在请求头携带 X-Admin-Key",
            },
        )


class SessionListResponse(BaseModel):
    """会话列表响应。"""

    total: int
    count: int
    sessions: list[dict] = Field(default_factory=list)


class SessionDetailResponse(BaseModel):
    """会话详情响应。"""

    session: dict
    message_count: int
    messages: list[dict] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """搜索响应。"""

    query: str
    count: int
    messages: list[dict] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    """反馈请求体。"""

    session_id: str = Field(..., min_length=1, description="会话 id")
    score: int = Field(..., description="1=👍  -1=👎")
    message_id: int | None = Field(default=None, description="关联消息 id（可选）")
    comment: str | None = Field(default=None, max_length=500, description="可选评论")


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="会话列表",
    dependencies=[Depends(require_admin_key)],
)
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=200, description="每页条数"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> SessionListResponse:
    """按最近活跃顺序返回会话列表。"""
    sessions = log_store.list_sessions(limit=limit, offset=offset)
    return SessionListResponse(
        total=log_store.stats()["total_sessions"],
        count=len(sessions),
        sessions=sessions,
    )


@router.get(
    "/stats",
    summary="会话统计",
    dependencies=[Depends(require_admin_key)],
)
async def stats() -> dict:
    """返回会话数、消息数、转人工会话数与意图分布。"""
    return log_store.stats()


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="搜索消息",
    dependencies=[Depends(require_admin_key)],
)
async def search(
    q: str = Query(..., min_length=1, description="关键词"),
    limit: int = Query(default=50, ge=1, le=200),
) -> SearchResponse:
    """按关键词模糊搜索消息内容。"""
    messages = log_store.search_messages(q, limit=limit)
    return SearchResponse(query=q, count=len(messages), messages=messages)


@router.post(
    "/feedback",
    summary="记录用户反馈（👍 / 👎）",
    dependencies=[Depends(require_admin_key)],
)
async def record_feedback(payload: FeedbackRequest) -> dict:
    """记录一条用户对某条回复的反馈。

    用于：
        - 评估回复质量（人工标注数据集）
        - 监控模型表现趋势
    """
    if payload.score not in (1, -1):
        raise HTTPException(
            status_code=422,
            detail="score 必须为 1（👍）或 -1（👎）",
        )
    if not log_store.record_feedback(
        payload.session_id,
        score=payload.score,
        message_id=payload.message_id,
        comment=(payload.comment or "").strip() or None,
    ):
        raise HTTPException(status_code=500, detail="反馈写入失败")
    return {
        "session_id": payload.session_id,
        "score": payload.score,
        "recorded": True,
    }


@router.get(
    "/feedback/stats",
    summary="反馈汇总统计",
    dependencies=[Depends(require_admin_key)],
)
async def feedback_stats() -> dict:
    """返回总 👍 / 总 👎 / 好评率 / 各会话反馈 / 最近 20 条。"""
    return log_store.feedback_stats()


@router.get(
    "/sessions/{session_id}/feedback",
    summary="某会话的全部反馈",
    dependencies=[Depends(require_admin_key)],
)
async def session_feedback(session_id: str) -> dict:
    """返回某会话的全部反馈记录。"""
    items = log_store.get_feedback_for_session(session_id)
    return {"session_id": session_id, "count": len(items), "items": items}


@router.delete(
    "/sessions/{session_id}",
    summary="删除会话日志",
    dependencies=[Depends(require_admin_key)],
)
async def delete_session(session_id: str) -> dict:
    """删除某会话及其全部消息日志。"""
    if not log_store.delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"未找到会话日志：{session_id}")
    return {"session_id": session_id, "deleted": True}


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetailResponse,
    summary="会话详情",
    dependencies=[Depends(require_admin_key)],
)
async def get_session(
    session_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> SessionDetailResponse:
    """返回某会话的汇总信息与全部消息 + 反馈列表。"""
    session = log_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话日志：{session_id}")
    messages = log_store.get_messages(session_id, limit=limit, offset=offset)
    feedback = log_store.get_feedback_for_session(session_id)
    # 把 feedback 按 message_id 索引
    fb_by_msg: dict[int, list[dict]] = {}
    for fb in feedback:
        mid = fb.get("message_id")
        if mid is not None:
            fb_by_msg.setdefault(mid, []).append(fb)
    # 给每条 message 加 feedback 列表（如果有）
    for m in messages:
        mid = m.get("id")
        if mid in fb_by_msg:
            m["feedback"] = fb_by_msg[mid]
    return SessionDetailResponse(
        session=session,
        message_count=len(messages),
        messages=messages,
    )


def _to_markdown(session: dict, messages: list[dict]) -> str:
    """把会话渲染成 Markdown（便于贴到工单 / 邮件 / Notion）。"""
    sid = session.get("session_id", "?")
    lines: list[str] = []
    lines.append(f"# 会话记录 · `{sid}`")
    lines.append("")
    lines.append(f"- 创建时间：`{session.get('created_at', '')}`")
    lines.append(f"- 最近活跃：`{session.get('updated_at', '')}`")
    lines.append(f"- 消息条数：**{session.get('message_count', 0)}**")
    lines.append(f"- 最近意图：`{session.get('last_intent', '')}`")
    lines.append(f"- 转人工次数：**{session.get('transferred_count', 0)}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    for m in messages:
        role = "👤 用户" if m.get("role") == "user" else "🤖 助手"
        ts = m.get("created_at", "")
        intent = m.get("intent")
        intent_label = INTENT_LABELS.get(intent, intent) if intent else ""
        meta_bits: list[str] = []
        if intent_label:
            meta_bits.append(f"意图={intent_label}")
        if m.get("order_no"):
            meta_bits.append(f"订单={m['order_no']}{'（未找到）' if not m.get('order_found') else ''}")
        if m.get("transferred"):
            meta_bits.append("**已转人工**")
        meta_str = f" _（{' · '.join(meta_bits)}）_" if meta_bits else ""
        lines.append(f"### {role}{meta_str}")
        lines.append(f"<sub>{ts}</sub>")
        lines.append("")
        content = str(m.get("content", "")).strip()
        lines.append(content if content else "_（空消息）_")
        lines.append("")
    return "\n".join(lines)


@router.get(
    "/sessions/{session_id}/export",
    summary="导出会话（JSON / Markdown）",
    dependencies=[Depends(require_admin_key)],
)
async def export_session(
    session_id: str,
    format: str = Query(default="md", pattern="^(md|json)$", description="导出格式：md / json"),
):
    """把单会话导出为 Markdown（默认）或 JSON，供工单 / 复盘使用。"""
    session = log_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话日志：{session_id}")
    messages = log_store.get_messages(session_id, limit=1000, offset=0)

    if format == "json":
        body = json.dumps(
            {
                "session": session,
                "messages": messages,
                "exported_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            },
            ensure_ascii=False,
            indent=2,
        )
        media_type = "application/json; charset=utf-8"
    else:
        body = _to_markdown(session, messages)
        media_type = "text/markdown; charset=utf-8"

    return PlainTextResponse(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="session-{session_id[:12]}-{datetime.utcnow().strftime("%Y%m%d")}.{format}"'
            ),
        },
    )
