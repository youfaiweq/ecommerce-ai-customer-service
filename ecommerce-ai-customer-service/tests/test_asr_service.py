"""离线 ASR（faster-whisper）服务测试。

完全离线：
  * 默认 fixture 注入假 ``WhisperModel``，不下载 / 推理
  * 真实 ``faster-whisper`` 代码路径通过 mock 验证
"""
from __future__ import annotations

import io
from collections.abc import Iterator

import pytest

from app.services.asr_service import ASRError, ASRResult, ASRService


class FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class FakeInfo:
    def __init__(self, language: str = "zh", duration: float = 1.5) -> None:
        self.language = language
        self.duration = duration


class FakeWhisperModel:
    """最小 fake faster-whisper 模型：返回固定的 segments 列表。"""

    def __init__(self, language: str = "zh", duration: float = 1.5) -> None:
        self.language = language
        self.duration = duration
        self.calls: list[dict] = []

    def transcribe(
        self,
        audio,
        *,
        language=None,
        beam_size=5,
        vad_filter=False,
    ) -> tuple[Iterator[FakeSegment], FakeInfo]:
        # 验证 audio 是 file-like
        assert hasattr(audio, "read"), "audio must be file-like"
        # 记录调用参数
        self.calls.append(
            {
                "language": language,
                "beam_size": beam_size,
                "vad_filter": vad_filter,
            }
        )
        segments = iter(
            [
                FakeSegment(0.0, 0.8, "你好"),
                FakeSegment(0.8, 1.5, "世界"),
            ]
        )
        info = FakeInfo(language=self.language, duration=self.duration)
        return segments, info


class TestASRService:
    """``ASRService`` 单测：注入 fake 模型完全离线。"""

    def test_disabled_raises(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", False)
        s = ASRService()
        with pytest.raises(ASRError) as exc_info:
            s.transcribe_file(io.BytesIO(b"\x00" * 100))
        assert exc_info.value.code == "asr_disabled"

    def test_empty_audio_raises(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        s = ASRService()
        s.set_model(FakeWhisperModel())
        with pytest.raises(ASRError) as exc_info:
            s.transcribe_file(io.BytesIO(b""))
        assert exc_info.value.code == "asr_empty_audio"

    def test_happy_path(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        s = ASRService()
        fake = FakeWhisperModel(language="zh", duration=1.5)
        s.set_model(fake)
        result = s.transcribe_file(io.BytesIO(b"\x00" * 1024))
        assert isinstance(result, ASRResult)
        assert result.text == "你好世界"
        assert result.language == "zh"
        assert result.duration_s == 1.5
        assert len(result.segments) == 2
        # 确认传给模型的语言参数 = None（auto 模式）
        assert fake.calls[0]["language"] is None

    def test_force_language(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        monkeypatch.setattr(settings, "asr_language", "zh")
        s = ASRService()
        fake = FakeWhisperModel(language="zh", duration=1.0)
        s.set_model(fake)
        s.transcribe_file(io.BytesIO(b"\x00" * 1024))
        assert fake.calls[0]["language"] == "zh"

    def test_audio_too_long(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        monkeypatch.setattr(settings, "asr_max_duration_s", 5)
        s = ASRService()
        s.set_model(FakeWhisperModel(duration=10.0))
        with pytest.raises(ASRError) as exc_info:
            s.transcribe_file(io.BytesIO(b"\x00" * 1024))
        assert exc_info.value.code == "asr_audio_too_long"

    def test_status_reflects_state(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        monkeypatch.setattr(settings, "asr_model_size", "small")
        s = ASRService()
        assert s.is_loaded is False
        assert s.status["enabled"] is True
        assert s.status["model_size"] == "small"
        s.set_model(FakeWhisperModel())
        assert s.is_loaded is True
        assert s.status["loaded"] is True

    def test_lazy_load_when_no_model(self, monkeypatch):
        """未注入模型时首次调用应触发加载（这里用 monkeypatch stub faster_whisper）。"""
        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        # 假 ``faster_whisper.WhisperModel``：只在被 import 时记录
        fake_module_calls = {"n": 0, "kwargs": None}
        fake_model = FakeWhisperModel()

        class FakeFasterWhisper:
            @staticmethod
            def WhisperModel(*_args, **kwargs):
                fake_module_calls["n"] += 1
                fake_module_calls["kwargs"] = kwargs
                return fake_model

        monkeypatch.setitem(
            __import__("sys").modules,
            "faster_whisper",
            FakeFasterWhisper,
        )
        s = ASRService()
        s._ensure_loaded()  # 不抛异常
        assert fake_module_calls["n"] == 1
        # 回归：必须用 faster-whisper 1.x 支持的 download_root，
        # 不能传 model_dir（ctranslate2 4.x 不再接受，会炸）
        assert "model_dir" not in fake_module_calls["kwargs"], (
            f"_ensure_loaded() 必须用 'download_root' 而非 'model_dir' "
            f"（faster-whisper 1.x + ctranslate2 4.x 兼容性）。实际传入: "
            f"{list(fake_module_calls['kwargs'].keys())}"
        )
        # download_root 应来自 settings.asr_model_dir（这里默认空 → None）
        assert "download_root" in fake_module_calls["kwargs"]

    def test_transcribe_error_wrapped(self, monkeypatch):
        """模型抛异常时包装为 ``asr_transcribe_failed``。"""
        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        s = ASRService()

        class BoomModel:
            def transcribe(self, audio, **kwargs):
                raise RuntimeError("decode failed")

        s.set_model(BoomModel())
        with pytest.raises(ASRError) as exc_info:
            s.transcribe_file(io.BytesIO(b"\x00" * 1024))
        assert exc_info.value.code == "asr_transcribe_failed"
        assert "decode failed" in (exc_info.value.detail or "")

    def test_load_network_error_classified(self, monkeypatch):
        """加载时若网络不可达，应返回 ``asr_model_download_failed`` 而不是通用错误。"""
        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        s = ASRService()

        # Stub 整个 ``_ensure_loaded``，触发网络错误
        from app.services import asr_service as mod

        def fake_ensure(self):
            raise ASRError(
                "asr_model_download_failed",
                "无法下载 faster-whisper 模型 small：网络不可达",
                detail="ConnectError: [Errno 10060]",
            )

        monkeypatch.setattr(mod.ASRService, "_ensure_loaded", fake_ensure)
        with pytest.raises(ASRError) as exc_info:
            s.transcribe_file(io.BytesIO(b"\x00" * 1024))
        assert exc_info.value.code == "asr_model_download_failed"
        assert "网络" in exc_info.value.message


class TestAudioAPI:
    """/chat/audio HTTP 接口测试（fake 模型 + TestClient）。"""

    def test_chat_audio_disabled_returns_503(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", False)
        from app.main import app

        client = TestClient(app)
        resp = client.post(
            "/chat/audio",
            files={"file": ("test.webm", b"\x00\x01\x02", "audio/webm")},
        )
        assert resp.status_code == 503
        body = resp.json()
        # 全局错误处理器会保留 detail 中的 code/message（dict 形式）
        assert "error" in body
        assert body["error"]["code"] == "asr_disabled"
        assert "ASR" in body["error"]["message"]

    def test_chat_audio_happy_path(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        from app.main import app
        from app.services.asr_service import asr_service

        asr_service.set_model(FakeWhisperModel(language="zh", duration=1.5))

        client = TestClient(app)
        # 一段小型二进制音频内容
        audio_bytes = b"\x00" * 1024
        resp = client.post(
            "/chat/audio",
            files={"file": ("test.webm", audio_bytes, "audio/webm")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["text"] == "你好世界"
        assert body["language"] == "zh"
        assert body["duration_s"] == 1.5
        assert len(body["segments"]) == 2

        # 重要：不应当污染全局 asr_service；清理
        asr_service._model = None  # type: ignore[attr-defined]

    def test_chat_audio_empty_422(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        from app.main import app
        from app.services.asr_service import asr_service

        asr_service.set_model(FakeWhisperModel())
        client = TestClient(app)
        resp = client.post(
            "/chat/audio",
            files={"file": ("test.webm", b"", "audio/webm")},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "asr_empty_audio"
        assert "音频" in body["error"]["message"]
        asr_service._model = None  # type: ignore[attr-defined]

    def test_chat_audio_rejects_oversized_upload(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import settings

        monkeypatch.setattr(settings, "asr_enabled", True)
        monkeypatch.setattr(settings, "asr_max_upload_bytes", 1)
        from app.main import app

        resp = TestClient(app).post(
            "/chat/audio",
            files={"file": ("large.webm", b"12", "audio/webm")},
        )
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "asr_file_too_large"

    def test_asr_status_endpoint(self):
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        resp = client.get("/asr/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "enabled" in body
        assert "loaded" in body
        assert "model_size" in body
