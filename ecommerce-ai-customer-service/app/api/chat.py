"""对话路由。

仅负责协议层（参数校验 / 响应组装），业务逻辑全部委托给 ``chat_service``。
完整链路：意图识别 → 知识库检索 → Prompt 组装 → 大模型生成 → 转人工判定。

接口：
    POST   /chat                 发送一条消息，返回回复 + 意图 + 引用来源
    POST   /chat/stream          SSE 流式响应（首包 meta → 增量 delta → 末包 done）
    GET    /chat/{session_id}    查看会话历史
    DELETE /chat/{session_id}    清空会话历史

鉴权（可选）：
    登录用户在 meta 事件中携带 ``user_id``，未登录时该字段为 ``null``。
    登录后会话绑定 user_id（写入 slot ``_user_id``），便于后续业务查询与日志归属。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user_optional
from app.services.chat_service import chat_service
from app.services.dialogue_manager import dialogue_manager
from app.services.llm_service import LLMError
from app.services.log_store import log_store
from app.utils.logging import log_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# 会话槽位键名：登录用户的绑定标识（仅业务用途，不参与对话生成）
SLOT_USER_ID = "_user_id"
SLOT_SESSION_SECRET_HASH = "_session_secret_hash"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    session_id: str | None = Field(
        default=None,
        description="会话 id；不传则自动新建会话",
    )
    session_token: str | None = Field(
        default=None,
        min_length=16,
        max_length=256,
        description="匿名会话凭证；首次请求由服务端签发",
    )
    provider: Literal["deepseek", "ollama"] = Field(
        default="deepseek",
        description="模型服务商；仅允许后端预设的 DeepSeek 或本地 Ollama",
    )


class ChatResponse(BaseModel):
    reply: str = Field(..., description="模型回复")
    session_id: str = Field(..., description="会话 id")
    user_id: str | None = Field(None, description="当前登录用户 id；未登录为 null")
    session_token: str | None = Field(None, description="匿名会话凭证；登录会话为 null")
    provider: Literal["deepseek", "ollama"] = Field(..., description="本轮实际使用的模型服务商")
    intent: dict = Field(default_factory=dict, description="意图识别结果")
    sources: list[dict] = Field(
        default_factory=list, description="引用的知识库 FAQ（含相关度得分）"
    )
    transferred: bool = Field(False, description="是否已（提示）转人工")
    grounded: bool = Field(False, description="是否命中知识库")
    order_no: str | None = Field(None, description="本次涉及的订单号")
    order_found: bool = Field(False, description="是否查询到订单")


class HistoryResponse(BaseModel):
    session_id: str
    user_id: str | None = Field(None, description="会话归属用户；未登录为 null")
    session_token: str | None = Field(None, description="匿名会话凭证；登录会话为 null")
    messages: list[dict[str, str]] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    """用户对一条 bot 回复的反馈（无需鉴权，按 session_id 归属即可）。"""

    score: int = Field(..., description="1=👍  -1=👎")
    message_id: int | None = Field(default=None, description="关联消息 id")
    comment: str | None = Field(default=None, max_length=500)


class FeedbackResponse(BaseModel):
    session_id: str
    score: int
    recorded: bool


def _bind_session_user(session_id: str, user_id: str | None) -> None:
    """把 user_id 写入会话槽位与日志库；未登录则跳过。"""
    if user_id:
        dialogue_manager.set_slot(session_id, SLOT_USER_ID, str(user_id))
        # 同步绑定到 LogStore 的 sessions.user_id 列（失败不影响主流程）
        log_store.set_session_user(session_id, str(user_id))


def _get_session_owner(session_id: str) -> str | None:
    """从内存或持久化日志取会话归属，兼容服务重启后的会话。"""
    return dialogue_manager.get_slot(session_id, SLOT_USER_ID) or log_store.get_session_owner(session_id)


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_session_secret_hash(session_id: str) -> str | None:
    return (
        dialogue_manager.get_slot(session_id, SLOT_SESSION_SECRET_HASH)
        or log_store.get_session_secret_hash(session_id)
    )


def _session_exists(session_id: str) -> bool:
    return dialogue_manager.session_exists(session_id) or log_store.get_session(session_id) is not None


def _require_session_access(
    session_id: str, user_id: str | None, session_token: str | None = None
) -> str | None:
    """校验会话归属；匿名会话必须提交首次签发的随机凭证。"""
    owner = _get_session_owner(session_id)
    if owner:
        if str(owner) == str(user_id or ""):
            return None
        raise HTTPException(
            status_code=403,
            detail={
                "code": "session_forbidden",
                "message": "无权访问该会话",
            },
        )

    expected_hash = _get_session_secret_hash(session_id)
    if expected_hash:
        provided_hash = _hash_session_token(session_token or "")
        if hmac.compare_digest(expected_hash, provided_hash):
            return session_token
        raise HTTPException(
            status_code=403,
            detail={
                "code": "session_token_invalid",
                "message": "匿名会话凭证无效，请重新开始对话",
            },
        )

    if _session_exists(session_id):
        # 旧版本创建且没有凭证的匿名会话不再可恢复，避免继续把 session_id 当授权凭据。
        raise HTTPException(
            status_code=403,
            detail={
                "code": "session_upgrade_required",
                "message": "该匿名会话需要重新开始，以启用安全保护",
            },
        )

    if user_id:
        return None

    token = secrets.token_urlsafe(32)
    token_hash = _hash_session_token(token)
    dialogue_manager.set_slot(session_id, SLOT_SESSION_SECRET_HASH, token_hash)
    log_store.set_session_secret_hash(session_id, token_hash)
    return token


@router.post("", response_model=ChatResponse, summary="发送消息并获取回复")
async def chat(
    request: ChatRequest,
    current_user: dict | None = Depends(get_current_user_optional),
) -> ChatResponse:
    """核心对话接口（含意图识别与知识库 RAG）。

    登录态：把 user_id 绑定到 session 槽位并在响应中回传；未登录时 user_id 为 null。
    """
    user_id = current_user["user_id"] if current_user else None
    session_id = request.session_id or dialogue_manager.new_session_id()
    session_token = _require_session_access(session_id, user_id, request.session_token)
    _bind_session_user(session_id, user_id)
    if user_id:
        session_token = None
    try:
        result = await chat_service.chat(
            session_id, request.message, user_id=user_id, provider=request.provider
        )
    except LLMError as exc:
        logger.warning("会话 %s 对话失败: %s", session_id, exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "llm_unavailable",
                "message": "智能客服暂时不可用，请稍后重试",
            },
        ) from exc
    payload = result.to_dict()
    payload["user_id"] = user_id
    payload["session_token"] = session_token
    payload["provider"] = request.provider
    return ChatResponse(**payload)


# ----------------------------------------------------------------------
# 流式响应（SSE）
# ----------------------------------------------------------------------
def _sse_format(event: str, data: dict) -> str:
    """组装单条 SSE 事件。"""
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


async def _chat_stream_events(
    session_id: str,
    message: str,
    user_id: str | None,
    session_token: str | None,
    provider: Literal["deepseek", "ollama"],
) -> AsyncIterator[str]:
    """逐事件产出 SSE 文本；在 meta / done 事件中注入用户与模型来源。"""
    try:
        async for ev in chat_service.chat_stream(
            session_id, message, user_id=user_id, provider=provider
        ):
            data = dict(ev["data"])
            if ev["event"] in ("meta", "done"):
                data["user_id"] = user_id
                data["provider"] = provider
            if ev["event"] == "meta":
                data["session_token"] = session_token
            yield _sse_format(ev["event"], data)
    except LLMError as exc:
        logger.warning("SSE 流式对话失败: %s", exc)
        yield _sse_format("error", {"message": "智能客服暂时不可用，请稍后重试"})
    except Exception:  # noqa: BLE001
        logger.exception("SSE 流式异常")
        yield _sse_format("error", {"message": "服务暂时不可用，请稍后重试"})


@router.post("/stream", summary="SSE 流式对话")
async def chat_stream(
    request: ChatRequest,
    current_user: dict | None = Depends(get_current_user_optional),
) -> StreamingResponse:
    """流式对话：返回 text/event-stream。

    事件序列：
        event=meta   → 首包，data 含 session_id / user_id / intent / sources / order_no / order_found
        event=delta  → 多次，data.text 为增量文本片段
        event=done   → 末包，data 含 user_id / transferred / grounded / order_no / order_found
        event=error  → 出错时单次

    user_id 字段：登录时为字符串，未登录为 null。
    """
    user_id = current_user["user_id"] if current_user else None
    session_id = request.session_id or dialogue_manager.new_session_id()
    session_token = _require_session_access(session_id, user_id, request.session_token)
    _bind_session_user(session_id, user_id)
    if user_id:
        session_token = None
    return StreamingResponse(
        _chat_stream_events(
            session_id, request.message, user_id, session_token, request.provider
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx：禁用缓冲
            "X-Session-Id": session_id,
        },
    )


@router.get("/{session_id}", response_model=HistoryResponse, summary="查看会话历史")
async def get_history(
    session_id: str,
    current_user: dict | None = Depends(get_current_user_optional),
    session_token: str | None = None,
) -> HistoryResponse:
    if not dialogue_manager.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    session_token = _require_session_access(
        session_id, current_user["user_id"] if current_user else None, session_token
    )
    user_id = dialogue_manager.get_slot(session_id, SLOT_USER_ID)
    return HistoryResponse(
        session_id=session_id,
        user_id=user_id,
        session_token=session_token,
        messages=dialogue_manager.get_history(session_id),
    )


@router.delete("/{session_id}", summary="清空会话历史")
async def clear_history(
    session_id: str,
    current_user: dict | None = Depends(get_current_user_optional),
    session_token: str | None = None,
) -> dict:
    _require_session_access(session_id, current_user["user_id"] if current_user else None, session_token)
    if not dialogue_manager.clear_history(session_id):
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return {"session_id": session_id, "cleared": True}


@router.post(
    "/{session_id}/feedback",
    response_model=FeedbackResponse,
    summary="对某条 bot 回复提交 👍 / 👎",
)
async def submit_feedback(
    session_id: str,
    payload: FeedbackRequest,
    current_user: dict | None = Depends(get_current_user_optional),
    session_token: str | None = None,
) -> FeedbackResponse:
    """前端用户对某条回复表态。无需鉴权（按 session_id 归属）。"""
    if payload.score not in (1, -1):
        raise HTTPException(
            status_code=422,
            detail="score 必须为 1（👍）或 -1（👎）",
        )
    _require_session_access(session_id, current_user["user_id"] if current_user else None, session_token)
    if not log_store.record_feedback(
        session_id,
        score=payload.score,
        message_id=payload.message_id,
        comment=(payload.comment or "").strip() or None,
    ):
        raise HTTPException(status_code=500, detail="反馈写入失败")
    log_event(
        "feedback.recorded",
        session_id=session_id,
        score=payload.score,
        with_comment=bool(payload.comment),
    )
    return FeedbackResponse(session_id=session_id, score=payload.score, recorded=True)
