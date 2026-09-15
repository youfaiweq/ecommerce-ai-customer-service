"""WebSocket 流式 ASR（``/asr/stream``）。

设计目标：把 MediaRecorder 的音频 chunk **边录边识别**，而不是录完
再一次性转写。

==========================================================================
协议
==========================================================================

Client → Server（文本帧）
::

    {"event": "start", "sample_rate": 16000, "language": "auto",
     "auto_send": false, "session_id": null}

Client → Server（二进制帧）：原始音频 bytes（webm/opus 或 wav 均可）

Client → Server（文本帧）
::

    {"event": "stop"}     # 完成录音，触发 final 识别并关闭连接

Server → Client（始终 JSON 文本）
::

    {"event": "ready",     "loaded": true, "model_size": "small"}
    {"event": "partial",   "text": "...", "language": "..."}   # 增量
    {"event": "final",     "text": "...", "language": "...",
                            "duration_s": 1.5, "segments": [...]}
    {"event": "error",     "code": "...", "message": "..."}
    {"event": "closed"}    # 主动断开

==========================================================================
策略
==========================================================================

1. 客户端发送二进制音频帧 → 服务端追加到 ``_buffer``（线程安全）
2. 一个 debounce 循环：每 ``partial_interval_ms`` 跑一次 faster-whisper
   识别，把结果作为 ``partial`` 推回去。期间即使数据还在追加，下一轮照样
   取**新一整段 buffer**（faster-whisper 不是真正可中断的，所以"增量识别"
   实为"重复识别最新完整 buffer"，客户端按 segments 增量渲染即可）。
3. 客户端发 ``stop`` → 服务端取消 debounce 任务、跑最后一次识别、发
   ``final``、发 ``closed``、关 WS。

==========================================================================
限制
==========================================================================

- 单容器同时跑很多路 WS 会吃光 CPU（每路都跑 faster-whisper）。
  这是有意设计：本机单用户场景优先，生产环境建议在客户端侧限并发。
- faster-whisper 不可中断：识别进行中的新一轮不会替换进行中的识别，
  只是结果可能延迟一个周期；这对单用户录制完全无感。
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.services.asr_service import ASRError, ASRResult, asr_service
from app.utils.logging import log_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------
PARTIAL_INTERVAL_MS_DEFAULT = 800   # 增量识别节流（避免反复跑模型）
PARTIAL_MIN_BUFFER_MS_DEFAULT = 500 # 缓冲达到这个时长才开始第一次 partial
FINAL_PARTIAL_INTERVAL_MS = 250     # 最后一次"临门一脚"识别间隔（更激进）


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------
@dataclass
class StreamConfig:
    """WebSocket 流式 ASR 的会话配置（来自 client 的 ``start`` 帧）。"""

    session_id: str | None = None
    sample_rate: int = 16000
    language: str | None = None       # None → 用 settings.asr_language
    auto_send: bool = False           # 仅日志用
    # 内部可调：服务端节流
    partial_interval_ms: int = PARTIAL_INTERVAL_MS_DEFAULT
    partial_min_buffer_ms: int = PARTIAL_MIN_BUFFER_MS_DEFAULT

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StreamConfig:
        return cls(
            session_id=d.get("session_id"),
            sample_rate=int(d.get("sample_rate") or 16000),
            language=d.get("language"),
            auto_send=bool(d.get("auto_send", False)),
            partial_interval_ms=int(
                d.get("partial_interval_ms") or PARTIAL_INTERVAL_MS_DEFAULT
            ),
            partial_min_buffer_ms=int(
                d.get("partial_min_buffer_ms") or PARTIAL_MIN_BUFFER_MS_DEFAULT
            ),
        )


@dataclass
class _PartialCache:
    """本会话累积状态（仅本会话用，不需要跨请求）。"""

    buffer: bytearray = field(default_factory=bytearray)
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_partial_text: str = ""
    last_partial_language: str = ""
    last_partial_at_ms: float = 0.0
    first_partial_at_ms: float = 0.0
    received_bytes: int = 0
    final_text: str | None = None     # finalize 后被锁定
    final_result: ASRResult | None = None


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _transcribe_bytes(data: bytes, *, language: str | None) -> ASRResult:
    """对一段完整的音频 byte 做识别（内部 helper，复用 asr_service）。

    faster-whisper 期望 file-like 对象，所以包一层 ``BytesIO``。
    """
    if not data:
        return ASRResult(text="", language="auto", duration_s=0.0, segments=[])
    buf = io.BytesIO(data)
    return asr_service.transcribe_file(
        buf,
        filename="stream.webm",
        language=language,
        beam_size=5,
    )


# ---------------------------------------------------------------------------
# 会话状态机（按 ws 连接维护一份）
# ---------------------------------------------------------------------------
class StreamingASRSession:
    """单条 WebSocket 连接的 ASR 会话状态。

    用法::

        sess = StreamingASRSession(config, send_json)
        sess.append(audio_bytes)
        # ... 更多 chunk ...
        final = await sess.finalize()  # 关停 debouncer 并跑最后一次
    """

    def __init__(self, config: StreamConfig, send_json) -> None:
        self.config = config
        self._send_json = send_json   # callable: dict -> awaitable
        self._state = _PartialCache()
        self._stop_event = asyncio.Event()
        self._debouncer_task: asyncio.Task | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # 写入音频
    # ------------------------------------------------------------------
    def append(self, data: bytes) -> None:
        """客户端送来一段二进制音频，写入缓冲。"""
        if not data or self._closed:
            return
        # 只有"final 后"或 stop 后才停止写
        with self._state.lock:
            self._state.buffer.extend(data)
            self._state.received_bytes += len(data)

    @property
    def received_bytes(self) -> int:
        return self._state.received_bytes

    # ------------------------------------------------------------------
    # 启动 debouncer（应在 append 前调用一次）
    # ------------------------------------------------------------------
    def start_debouncer(self, loop: asyncio.AbstractEventLoop) -> None:
        """启动后台节流循环：定期把累积 buffer 跑识别、回推 partial。

        参数 ``loop`` 用于在 worker 线程里 ``run_coroutine_threadsafe``
        把识别结果投回主 asyncio 队列（由 send_json 内部 await）。
        """
        if self._debouncer_task is not None:
            return
        self._state.first_partial_at_ms = 0.0
        self._debouncer_task = loop.create_task(self._debouncer_loop())

    async def _debouncer_loop(self) -> None:
        """以 ``partial_interval_ms`` 为周期唤醒，跑识别 / 发 partial。"""
        while not self._stop_event.is_set():
            # 用 asyncio.wait 而不是 sleep，便于 stop 时立即退出
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.config.partial_interval_ms / 1000.0,
                )
                # 如果是被 stop 唤醒的，退出
                break
            except TimeoutError:
                pass

            # 取出 buffer 快照（线程安全）
            with self._state.lock:
                if not self._state.buffer:
                    continue
                snap = bytes(self._state.buffer)
                received = self._state.received_bytes
                # 第一轮 partial 前再多等一会儿，确保有内容
                if self._state.first_partial_at_ms == 0.0:
                    self._state.first_partial_at_ms = time.monotonic() * 1000

            # 估算音频时长（很粗糙：基于字节数 / sample_rate / 2 字节/采样）
            approx_dur_ms = (len(snap) * 1000) // max(
                1, self.config.sample_rate * 2
            )
            # 跑识别（CPU 重活；放在事件循环 worker 中由线程池执行）
            # 把 snap 通过默认参数"冻结"到 lambda，避免循环变量被覆盖（B023）
            try:
                _snap = snap
                _lang = self.config.language or settings.asr_language
                result = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda snap=_snap, lang=_lang: _transcribe_bytes(snap, language=lang),
                )
            except ASRError as exc:
                # 网络/模型错误 → 推 error，但 debouncer 继续（等下次数据）
                await self._send_json(
                    {
                        "event": "error",
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
                continue
            except Exception as exc:  # noqa: BLE001
                logger.exception("streaming ASR transcribe failed")
                await self._send_json(
                    {
                        "event": "error",
                        "code": "asr_transcribe_failed",
                        "message": str(exc),
                    }
                )
                continue

            # 增量发送：只在 text 变化时推，避免前端无意义刷新
            new_text = result.text
            new_lang = result.language
            if (
                new_text != self._state.last_partial_text
                or new_lang != self._state.last_partial_language
            ):
                self._state.last_partial_text = new_text
                self._state.last_partial_language = new_lang
                await self._send_json(
                    {
                        "event": "partial",
                        "text": new_text,
                        "language": new_lang,
                        "received_bytes": received,
                        "approx_duration_ms": approx_dur_ms,
                    }
                )

    # ------------------------------------------------------------------
    # finalize：客户端发"stop"时调用
    # ------------------------------------------------------------------
    async def finalize(self) -> ASRResult:
        """停掉 debouncer，跑一次最终识别，返回结果。"""
        if self._closed:
            return self._state.final_result or ASRResult(
                text="", language="auto", duration_s=0.0, segments=[]
            )
        self._closed = True
        # 唤醒 debouncer 退出
        self._stop_event.set()
        if self._debouncer_task is not None:
            try:
                await asyncio.wait_for(self._debouncer_task, timeout=2.0)
            except TimeoutError:
                self._debouncer_task.cancel()
            self._debouncer_task = None

        with self._state.lock:
            snap = bytes(self._state.buffer)
            self._state.buffer.clear()

        if not snap:
            empty = ASRResult(
                text="", language="auto", duration_s=0.0, segments=[]
            )
            self._state.final_result = empty
            return empty

        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _transcribe_bytes(
                    snap,
                    language=self.config.language or settings.asr_language,
                ),
            )
        except ASRError as exc:
            log_event("asr.stream_failed", code=exc.code, detail=exc.message)
            raise
        finally:
            log_event(
                "asr.stream_done",
                duration_s=result.duration_s if "result" in locals() else 0.0,
                chars=len(result.text) if "result" in locals() else 0,
                received_bytes=len(snap),
            )

        self._state.final_result = result
        return result

    async def close(self) -> None:
        """主动关闭（连接断开 / 服务端异常）。不跑 final 识别。"""
        self._closed = True
        self._stop_event.set()
        if self._debouncer_task is not None:
            self._debouncer_task.cancel()
            self._debouncer_task = None
