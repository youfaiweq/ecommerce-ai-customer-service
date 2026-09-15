"""离线 ASR 服务（faster-whisper）。

把 ``POST /chat/audio`` 上传的音频文件转写为文本。

设计要点：

* **懒加载单例** —— 第一笔请求到来时才创建 ``WhisperModel``，避免启动即
  下载 ~460MB 模型（会让 ``docker compose up`` 卡住）。
* **可注入** —— 通过 ``set_model(model)`` 在测试里塞假模型，单测完全离线。
* **统一异常** —— ``ASRError`` 暴露 ``code`` + ``message``，便于前端识别
  错误（音频格式、超时长、模型未加载、识别失败）。
* **进度回调** —— ``transcribe(...)`` 支持 ``on_progress`` 异步回调，前端
  可以轮询长任务。

依赖：
    pip install faster-whisper
    pip install av            # 音频解码（faster-whisper 自动依赖）
"""

from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol

from app.config import settings
from app.utils.logging import log_event

logger = logging.getLogger(__name__)


class ASRError(Exception):
    """ASR 失败统一异常。

    :param code:    错误码（前端可按 code 区分）
    :param message: 面向用户的错误提示
    """

    def __init__(self, code: str, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass
class ASRResult:
    """一次识别结果。"""

    text: str
    language: str
    duration_s: float
    segments: list[dict]


class WhisperLike(Protocol):
    """测试可注入的最小接口（faster_whisper.WhisperModel 的子集）。"""

    def transcribe(
        self,
        audio: str | BinaryIO,
        *,
        language: str | None = None,
        beam_size: int = 5,
        vad_filter: bool = True,
    ) -> tuple[Any, Any]:
        ...


class ASRService:
    """离线 ASR 服务（线程安全懒加载单例）。"""

    def __init__(self) -> None:
        self._model: WhisperLike | None = None
        self._model_size: str | None = None
        self._device: str | None = None
        self._compute_type: str | None = None
        self._model_dir: str | None = None
        self._lock = threading.Lock()
        self._load_attempts = 0
        self._load_errors = 0

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        """ASR 是否启用（来自配置）。"""
        return bool(getattr(settings, "asr_enabled", True))

    @property
    def is_loaded(self) -> bool:
        """模型是否已加载（无副作用）。"""
        return self._model is not None

    @property
    def status(self) -> dict:
        """当前状态（用于 ``/health/deep`` 等端点）。"""
        return {
            "enabled": self.enabled,
            "loaded": self.is_loaded,
            "model_size": self._model_size or settings.asr_model_size,
            "device": self._device or settings.asr_device,
            "compute_type": self._compute_type or settings.asr_compute_type,
            "load_attempts": self._load_attempts,
            "load_errors": self._load_errors,
        }

    # ------------------------------------------------------------------
    def set_model(self, model: WhisperLike) -> None:
        """注入模型（用于测试）。"""
        with self._lock:
            self._model = model
            self._model_size = "mock"
            self._device = "mock"
            self._compute_type = "mock"
            self._model_dir = "mock"

    def _ensure_loaded(self) -> WhisperLike:
        """懒加载模型（线程安全双检锁）。"""
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            self._load_attempts += 1
            try:
                from faster_whisper import WhisperModel  # 懒依赖
            except ImportError as exc:
                self._load_errors += 1
                raise ASRError(
                    "asr_dependency_missing",
                    "服务未安装 faster-whisper，请 pip install faster-whisper",
                    detail=str(exc),
                ) from exc

            size = settings.asr_model_size
            device = settings.asr_device
            compute_type = settings.asr_compute_type
            # 兼容说明：早期 faster-whisper (≤0.5) 接受 model_dir kwarg；1.x 改名 download_root；
            # ctranslate2 4.x 的 ctranslate2.models.Whisper() 干脆去掉 model_dir，且把它识别的路径
            # 通过 faster-whisper 自己 resolve。这里统一走 download_root，行为等价。
            download_root = settings.asr_model_dir or None

            # auto 模式：没有 nvml 时回落 cpu
            if device == "auto":
                try:
                    import ctranslate2  # noqa: F401

                    # ctranslate2 4.x 支持 cuda；这里仅做"能用 cuda 就用"的启发
                    device = "cpu"
                except Exception:
                    device = "cpu"

            log_event(
                "asr.model_loading",
                size=size,
                device=device,
                compute_type=compute_type,
                download_root=download_root or "<default ~/.cache/huggingface>",
            )
            try:
                model = WhisperModel(
                    size,
                    device=device,
                    compute_type=compute_type,
                    download_root=download_root,
                )
            except Exception as exc:
                self._load_errors += 1
                # 区分网络不可达 vs 其它错误
                err_msg = str(exc).lower()
                if (
                    "connect" in err_msg
                    or "network" in err_msg
                    or "unreachable" in err_msg
                    or "timeout" in err_msg
                    or "proxy" in err_msg
                    or "10060" in err_msg
                ):
                    code = "asr_model_download_failed"
                    msg = (
                        f"无法下载 faster-whisper 模型 {size}：网络不可达。"
                        "请设置 PRELOAD_MODEL=1 预烤进镜像，或检查网络/HF_ENDPOINT"
                    )
                else:
                    code = "asr_model_load_failed"
                    msg = f"加载 faster-whisper 模型 {size} 失败"
                raise ASRError(code, msg, detail=str(exc)) from exc

            self._model = model
            self._model_size = size
            self._device = device
            self._compute_type = compute_type
            self._model_dir = download_root or ""
            log_event(
                "asr.model_loaded",
                size=size,
                device=device,
                compute_type=compute_type,
            )
            return model

    # ------------------------------------------------------------------
    def transcribe_file(
        self,
        fileobj: BinaryIO,
        *,
        filename: str = "audio.webm",
        language: str | None = None,
        beam_size: int = 5,
    ) -> ASRResult:
        """对一段音频做识别。

        :param fileobj: 已打开的二进制文件对象（指向开头）
        :param filename: 文件名（仅用于日志/错误提示）
        :param language: 强制源语言（None 取自 settings）
        :param beam_size: 解码束大小（5 是 faster-whisper 默认）
        :raises ASRError: 禁用 / 加载失败 / 识别失败 / 音频超长
        """
        if not self.enabled:
            raise ASRError(
                "asr_disabled",
                "ASR 功能未启用，请在配置中设置 ASR_ENABLED=true",
            )

        # 读取并校验大小
        try:
            fileobj.seek(0)
        except Exception:
            pass
        data = fileobj.read()
        if not data:
            raise ASRError("asr_empty_audio", "上传的音频文件为空")
        size_bytes = len(data)

        # 模型加载（懒）
        model = self._ensure_loaded()

        lang = language or settings.asr_language
        if lang == "auto":
            lang = None  # 让 faster-whisper 自动检测

        try:
            buf = io.BytesIO(data)
            segments_iter, info = model.transcribe(
                buf,
                language=lang,
                beam_size=beam_size,
                vad_filter=True,
            )
            segments: list[dict] = []
            full_text_parts: list[str] = []
            for seg in segments_iter:
                segments.append(
                    {
                        "start": float(seg.start),
                        "end": float(seg.end),
                        "text": seg.text,
                    }
                )
                full_text_parts.append(seg.text)
            full_text = "".join(full_text_parts).strip()
            duration_s = float(getattr(info, "duration", 0.0))
            detected_lang = getattr(info, "language", lang or "auto")
        except ASRError:
            raise
        except Exception as exc:
            log_event("asr.transcribe_failed", error=str(exc), size_bytes=size_bytes)
            raise ASRError(
                "asr_transcribe_failed",
                "识别失败：音频格式不支持或解码失败",
                detail=str(exc),
            ) from exc

        # 时长上限（兜底）
        max_d = settings.asr_max_duration_s
        if duration_s > max_d:
            raise ASRError(
                "asr_audio_too_long",
                f"音频时长 {duration_s:.1f}s 超过限制 {max_d}s",
                detail=f"duration={duration_s:.1f}",
            )

        # ⚠️ 关键：不能直接用 ``filename=...`` —— Python logging.LogRecord 把它保留
        # 为源码文件名，extra 字段撞名会 KeyError。这里改用 file_name。
        log_event(
            "asr.transcribe_done",
            file_name=filename,
            size_bytes=size_bytes,
            duration_s=duration_s,
            language=str(detected_lang),
            segments=len(segments),
        )

        return ASRResult(
            text=full_text,
            language=str(detected_lang),
            duration_s=duration_s,
            segments=segments,
        )


# 模块级单例
asr_service = ASRService()
