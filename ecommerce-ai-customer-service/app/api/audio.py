"""音频上传与 ASR 转写接口。

接口：

    POST /chat/audio                       纯转写（默认 multipart/form-data）
    POST /chat/audio?return_chat=true       转写并直接发起 /chat（一次性完成录音→对话）
    WS   /asr/stream                       流式 ASR（边录边识别，前端用 WebSocket）

    GET  /asr/status                       当前 ASR 模型状态（认证与 /chat/audio 一致）
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from app.api.chat import _bind_session_user, _require_session_access
from app.auth import get_current_user_optional
from app.auth.tokens import verify_token
from app.auth.users import get_user_by_id
from app.config import settings
from app.services.asr_service import ASRError, ASRResult, asr_service
from app.services.asr_stream import StreamConfig, StreamingASRSession
from app.services.chat_service import chat_service
from app.services.dialogue_manager import dialogue_manager
from app.utils.logging import log_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audio"])

_asr_stream_lock = threading.Lock()
_active_asr_streams = 0


def _try_reserve_asr_stream() -> bool:
    """保留一个流式 ASR 名额，避免并发转写耗尽 CPU。"""
    global _active_asr_streams
    with _asr_stream_lock:
        if _active_asr_streams >= settings.asr_stream_max_connections:
            return False
        _active_asr_streams += 1
        return True


def _release_asr_stream() -> None:
    global _active_asr_streams
    with _asr_stream_lock:
        _active_asr_streams = max(0, _active_asr_streams - 1)


# ===========================================================================
# 响应模型
# ===========================================================================
class AudioTranscribeResponse(BaseModel):
    """音频转写响应。"""

    text: str
    language: str
    duration_s: float
    segments: list[dict] = []
    session_id: str | None = None
    session_token: str | None = None
    reply: str | None = None  # ?return_chat=true 时附带 bot 回复
    intent: dict | None = None
    transferred: bool | None = None
    sources: list[str] | None = None


class ASRStatusResponse(BaseModel):
    """ASR 状态响应（健康检查用）。"""

    enabled: bool
    loaded: bool
    model_size: str
    device: str
    compute_type: str
    load_attempts: int
    load_errors: int


# ===========================================================================
# 音频转写
# ===========================================================================
@router.post(
    "/chat/audio",
    response_model=AudioTranscribeResponse,
    summary="上传音频并转写（faster-whisper）",
)
async def chat_audio(
    request: Request,
    file: UploadFile = File(..., description="音频文件（webm / wav / mp3 / m4a 等）"),
    session_id: str | None = Form(default=None, description="可选：会话 ID"),
    session_token: str | None = Form(default=None, description="匿名会话凭证"),
    language: str | None = Form(default=None, description="强制源语言（zh/en/auto）"),
    return_chat: bool = Query(default=False, description="转写后立即走 /chat 流程"),
    current_user: dict | None = Depends(get_current_user_optional),
) -> AudioTranscribeResponse:
    """把上传的音频转写为文本。

    * 关闭 ASR 功能时直接返回 503
    * 仅静音 / 文件为空 时返回 422
    * 失败统一抛 ``ASRError``（前端按 ``code`` 字段区分）
    * ``return_chat=true`` 时，转写成功后直接调用 ``chat_service.chat``
      把结果作为新一轮用户消息送入，返回最终 reply。
    """
    t0 = time.monotonic()
    if not asr_service.enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "asr_disabled",
                "message": "ASR 功能未启用，请设置 ASR_ENABLED=true",
            },
        )

    max_bytes = settings.asr_max_upload_bytes
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "asr_file_too_large",
                "message": f"音频文件不能超过 {max_bytes // (1024 * 1024)} MB",
            },
        )

    try:
        content = await file.read(max_bytes + 1)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "asr_read_failed", "message": "读取上传文件失败", "detail": str(exc)},
        ) from exc
    finally:
        await file.close()

    if not content:
        raise HTTPException(
            status_code=422,
            detail={"code": "asr_empty_audio", "message": "上传的音频文件为空"},
        )
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "asr_file_too_large",
                "message": f"音频文件不能超过 {max_bytes // (1024 * 1024)} MB",
            },
        )

    # 用 BytesIO 包一层（faster-whisper 接受 file-like）
    import io

    buf = io.BytesIO(content)
    filename = file.filename or "audio.webm"
    try:
        result: ASRResult = asr_service.transcribe_file(
            buf,
            filename=filename,
            language=language,
        )
    except ASRError as exc:
        code = exc.code
        # 503 表示"服务暂时不可用"（依赖缺失 / 模型下载失败 → 客户端可重试）
        # 422 表示"客户端请求有问题"（音频空、超时长、格式不支持）
        if code in (
            "asr_disabled",
            "asr_dependency_missing",
            "asr_model_load_failed",
            "asr_model_download_failed",
        ):
            status_code = 503
        else:
            status_code = 422
        raise HTTPException(
            status_code=status_code,
            detail=exc.to_dict(),
        ) from exc

    payload = AudioTranscribeResponse(
        text=result.text,
        language=result.language,
        duration_s=result.duration_s,
        segments=result.segments,
        session_id=None,
    )

    if return_chat and result.text:
        # 复用聊天会话的全部授权规则，不能让音频入口成为会话绕过路径。
        active_session_id = session_id or dialogue_manager.new_session_id()
        user_id = current_user["user_id"] if current_user else None
        active_session_token = _require_session_access(active_session_id, user_id, session_token)
        _bind_session_user(active_session_id, user_id)
        if user_id:
            active_session_token = None
        chat_result = await chat_service.chat(active_session_id, result.text, user_id=user_id)
        # 把 chat 返回的 session_id 回写
        payload.session_id = chat_result.session_id
        payload.session_token = active_session_token
        payload.reply = chat_result.reply
        payload.intent = chat_result.intent
        payload.transferred = chat_result.transferred
        payload.sources = [s.id for s in chat_result.sources] if chat_result.sources else None

    elapsed = int((time.monotonic() - t0) * 1000)
    log_event(
        "chat.audio",
        latency_ms=elapsed,
        transcribed=bool(result.text),
        duration_s=result.duration_s,
        language=result.language,
        return_chat=return_chat,
        session_id=payload.session_id,
    )
    return payload


# ===========================================================================
# ASR 状态
# ===========================================================================
@router.get(
    "/asr/status",
    response_model=ASRStatusResponse,
    summary="ASR 状态查询",
)
async def asr_status() -> ASRStatusResponse:
    """返回 ASR 当前是否启用 / 模型是否已加载 / 失败次数（用于 /health/deep + 调试）。"""
    s = asr_service.status
    return ASRStatusResponse(**s)


# ===========================================================================
# WebSocket 流式 ASR
# ===========================================================================
@router.websocket("/asr/stream")
async def asr_stream(ws: WebSocket) -> None:
    """流式 ASR（边录边识别）WebSocket 端点。

    **协议**（详见 ``app.services.asr_stream.StreamingASRSession``）：

    Client → Server（文本 JSON）：
        {"event": "start", "sample_rate": 16000, "language": "auto",
         "session_id": null, "token": "<Bearer token>"}
        {"event": "stop"}

    Client → Server（二进制）：MediaRecorder 原始音频 bytes

    Server → Client（始终 JSON）：
        {"event": "ready",     "loaded": bool, "model_size": "..."}
        {"event": "partial",   "text": "...", "language": "...",
                                "received_bytes": int, "approx_duration_ms": int}
        {"event": "final",     "text": "...", "language": "...",
                                "duration_s": float, "segments": [...]}
        {"event": "error",     "code": "...", "message": "..."}
        {"event": "closed"}
    """
    await ws.accept()
    if not asr_service.enabled:
        await ws.send_json(
            {
                "event": "error",
                "code": "asr_disabled",
                "message": "ASR 功能未启用，请设置 ASR_ENABLED=true",
            }
        )
        await ws.close(code=1011)
        return

    # ---- 等第一帧：必须是 start 文本 ----
    try:
        first = await asyncio.wait_for(ws.receive(), timeout=15)
    except TimeoutError:
        await ws.send_json(
            {"event": "error", "code": "asr_stream_timeout",
             "message": "等待 start 帧超时（15s）"}
        )
        await ws.close(code=4408)
        return
    except WebSocketDisconnect:
        return

    if first.get("type") != "websocket.receive":
        await ws.send_json(
            {"event": "error", "code": "asr_stream_protocol",
             "message": "首帧必须是文本且为 start"}
        )
        await ws.close(code=4400)
        return

    try:
        start_payload = json.loads(first.get("text") or "{}")
    except (ValueError, TypeError):
        await ws.send_json(
            {"event": "error", "code": "asr_stream_protocol",
             "message": "start 帧不是合法 JSON"}
        )
        await ws.close(code=4400)
        return

    if start_payload.get("event") != "start":
        await ws.send_json(
            {"event": "error", "code": "asr_stream_protocol",
             "message": "首帧必须是 {\"event\":\"start\", ...}"}
        )
        await ws.close(code=4400)
        return

    # 浏览器 WebSocket 不能可靠设置 Authorization header，因此只在首帧读取 token；
    # 它不出现在 URL、代理访问日志或错误响应中。
    token = start_payload.get("token")
    token_payload = verify_token(token) if isinstance(token, str) else None
    user = get_user_by_id(str(token_payload.get("user_id", ""))) if token_payload else None
    if user is None:
        await ws.send_json(
            {"event": "error", "code": "asr_unauthorized", "message": "请先登录后使用语音识别"}
        )
        await ws.close(code=4401)
        return

    try:
        cfg = StreamConfig.from_dict(start_payload)
    except (ValueError, TypeError) as exc:
        await ws.send_json(
            {"event": "error", "code": "asr_stream_protocol",
             "message": f"start 参数非法: {exc}"}
        )
        await ws.close(code=4400)
        return

    if not _try_reserve_asr_stream():
        await ws.send_json(
            {"event": "error", "code": "asr_stream_busy", "message": "语音识别繁忙，请稍后重试"}
        )
        await ws.close(code=4429)
        return

    loop = asyncio.get_running_loop()

    async def send_json(payload: dict) -> None:
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001
            pass

    sess = StreamingASRSession(cfg, send_json)

    # ---- ready ----
    status = asr_service.status
    await send_json(
        {
            "event": "ready",
            "loaded": status["loaded"],
            "model_size": status["model_size"],
            "received_bytes": 0,
        }
    )

    sess.start_debouncer(loop)
    log_event(
        "asr.stream_open",
        session_id=cfg.session_id,
        sample_rate=cfg.sample_rate,
        language=cfg.language or "auto",
    )

    # ---- 主循环：直到 client stop / disconnect ----
    try:
        while True:
            try:
                msg = await ws.receive()
            except WebSocketDisconnect:
                break

            mtype = msg.get("type")
            if mtype == "websocket.disconnect":
                break

            if mtype != "websocket.receive":
                continue

            # ---- 二进制 → 写 buffer ----
            if msg.get("bytes") is not None:
                if sess.received_bytes + len(msg["bytes"]) > settings.asr_stream_max_bytes:
                    await send_json(
                        {
                            "event": "error",
                            "code": "asr_stream_too_large",
                            "message": "音频流超过大小限制，请缩短录音后重试",
                        }
                    )
                    break
                sess.append(msg["bytes"])
                continue

            # ---- 文本 → 控制命令 ----
            text = msg.get("text")
            if not text:
                continue
            try:
                payload = json.loads(text)
            except (ValueError, TypeError):
                continue
            ev = payload.get("event")
            if ev == "stop":
                # run final + send + close
                try:
                    result = await sess.finalize()
                except ASRError as exc:
                    await send_json(
                        {"event": "error", "code": exc.code,
                         "message": exc.message}
                    )
                    break
                await send_json(
                    {
                        "event": "final",
                        "text": result.text,
                        "language": result.language,
                        "duration_s": result.duration_s,
                        "segments": result.segments,
                        "received_bytes": sess.received_bytes,
                    }
                )
                log_event(
                    "asr.stream_close",
                    session_id=cfg.session_id,
                    duration_s=result.duration_s,
                    chars=len(result.text),
                    received_bytes=sess.received_bytes,
                )
                break
            # 其它 event：忽略
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("WS 流式 ASR 异常")
        await send_json(
            {"event": "error", "code": "asr_stream_internal",
             "message": "语音识别服务暂时不可用，请稍后重试"}
        )
    finally:
        await sess.close()
        try:
            await send_json({"event": "closed"})
        except Exception:  # noqa: BLE001
            pass
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
        _release_asr_stream()
