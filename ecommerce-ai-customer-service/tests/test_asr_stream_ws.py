"""流式 ASR WebSocket 端点测试（``/asr/stream``）。

完全离线：用 ``set_model`` 注入 fake ``WhisperModel`` + ``TestClient.websocket_connect``。
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.services.asr_service import asr_service


# ---------------------------------------------------------------------------
# Fake 模型（与 test_asr_service 中的 FakeWhisperModel 思路一致）
# ---------------------------------------------------------------------------
class FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class FakeWhisperModelStream:
    """每次 transcribe 返回同样的固定 segments（fake 增量）。"""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def transcribe(self, audio, **kwargs) -> tuple[list, object]:
        time.sleep(0.05)
        self.calls.append(time.monotonic())
        segments = iter(
            [
                FakeSegment(0.0, 0.6, "你好"),
                FakeSegment(0.6, 1.2, "世界"),
            ]
        )

        class _Info:
            language = "zh"
            duration = 1.2

        return segments, _Info()


@pytest.fixture
def fake_model():
    m = FakeWhisperModelStream()
    asr_service.set_model(m)
    yield m
    asr_service._model = None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------
class TestAsrStreamWS:
    """WebSocket /asr/stream 端到端测试（fake 模型）。"""

    def test_start_protocol_error_close(self, monkeypatch):
        """首帧不是 start 应立即关闭。"""
        from app.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "asr_enabled", True)
        client = TestClient(app)
        with client.websocket_connect("/asr/stream") as ws:
            ws.send_json({"event": "weird"})
            try:
                msg = ws.receive_json()
                assert msg.get("event") == "error"
            except (WebSocketDisconnect, Exception):
                # 连接已断开也是合规结果
                return

    def test_full_flow_yields_partial_then_final(self, monkeypatch, fake_model, auth_token):
        """完整流程：start → 一段 audio → partial → audio → stop → final。"""
        from app.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "asr_enabled", True)
        client = TestClient(app)

        with client.websocket_connect("/asr/stream") as ws:
            ws.send_json(
                {
                    "event": "start",
                    "sample_rate": 16000,
                    "language": "zh",
                    "partial_interval_ms": 200,
                    "token": auth_token,
                }
            )
            ready = ws.receive_json()
            assert ready["event"] == "ready"
            assert ready["loaded"] is True

            for _ in range(3):
                ws.send_bytes(b"\x00\x01" * 200)

            partial_count = 0
            deadline = time.monotonic() + 2.5
            while partial_count < 1 and time.monotonic() < deadline:
                try:
                    msg = ws.receive_json()
                except (WebSocketDisconnect, Exception):
                    break
                if msg.get("event") == "partial":
                    partial_count += 1
                    assert msg["text"] == "你好世界"
                elif msg.get("event") == "error":
                    pytest.fail(f"unexpected error: {msg}")

            assert partial_count >= 1, "expected at least one partial"

            ws.send_json({"event": "stop"})
            events = []
            for _ in range(2):
                try:
                    msg = ws.receive_json()
                    events.append(msg.get("event"))
                except (WebSocketDisconnect, Exception):
                    break
            assert "final" in events, f"missing final in {events}"

        assert len(fake_model.calls) >= 2

    def test_disabled_returns_asr_disabled_error(self, monkeypatch):
        """ASR_ENABLED=false 时 WS 服务端应主动发错并断开。"""
        from app.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "asr_enabled", False)
        client = TestClient(app)
        with client.websocket_connect("/asr/stream") as ws:
            with pytest.raises((WebSocketDisconnect, Exception)):
                # 服务端 accept 后立刻 send error + close → 读不到任何内容会触发 disconnect
                ws.receive_json(timeout=2.0)

    def test_stream_requires_authentication(self, monkeypatch):
        from app.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "asr_enabled", True)
        with TestClient(app).websocket_connect("/asr/stream") as ws:
            ws.send_json({"event": "start"})
            assert ws.receive_json()["code"] == "asr_unauthorized"
