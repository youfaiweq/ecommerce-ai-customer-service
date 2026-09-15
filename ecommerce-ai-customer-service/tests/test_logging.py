"""结构化日志 + 上下文测试。"""

from __future__ import annotations

import io
import json
import logging

from app.utils.logging import (
    JsonFormatter,
    bind_context,
    clear_context,
    log_event,
    measure_ms,
)


def _capture_log_output() -> tuple[logging.Handler, io.StringIO]:
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(JsonFormatter(redact=True))
    return h, buf


class TestJsonFormatter:
    def test_basic_json(self):
        h, buf = _capture_log_output()
        logger = logging.getLogger("test_basic")
        logger.handlers = [h]
        logger.setLevel(logging.INFO)
        logger.info("hello %s", "world")
        line = buf.getvalue().strip()
        payload = json.loads(line)
        assert payload["level"] == "INFO"
        assert payload["logger"] == "test_basic"
        assert payload["msg"] == "hello world"

    def test_pii_redaction(self):
        h, buf = _capture_log_output()
        logger = logging.getLogger("test_pii")
        logger.handlers = [h]
        logger.setLevel(logging.INFO)
        logger.info("user msg %s", "我的手机 13812345678")
        payload = json.loads(buf.getvalue().strip())
        assert "13812345678" not in payload["msg"]
        assert "138****5678" in payload["msg"]

    def test_context(self):
        h, buf = _capture_log_output()
        logger = logging.getLogger("test_ctx")
        logger.handlers = [h]
        logger.setLevel(logging.INFO)
        bind_context(request_id="abc123", session_id="sess1")
        try:
            logger.info("hi")
            payload = json.loads(buf.getvalue().strip())
            assert payload["ctx"]["request_id"] == "abc123"
            assert payload["ctx"]["session_id"] == "sess1"
        finally:
            clear_context()

    def test_extra_fields(self):
        h, buf = _capture_log_output()
        logger = logging.getLogger("test_extra")
        logger.handlers = [h]
        logger.setLevel(logging.INFO)
        logger.info("event", extra={"latency_ms": 123, "model": "gpt-4o-mini"})
        payload = json.loads(buf.getvalue().strip())
        assert payload["latency_ms"] == 123
        assert payload["model"] == "gpt-4o-mini"


class TestLogEvent:
    def test_log_event(self):
        h, buf = _capture_log_output()
        root = logging.getLogger()
        saved = list(root.handlers)
        root.handlers = [h]
        root.setLevel(logging.INFO)
        try:
            log_event("test.event", value=42)
            payload = json.loads(buf.getvalue().strip())
            # event name appears both as msg (record.getMessage()) and in ctx
            assert payload["msg"] == "test.event"
            assert payload["ctx"]["event"] == "test.event"
            assert payload["value"] == 42
        finally:
            root.handlers = saved
            clear_context()


class TestMeasureMs:
    def test_returns_int(self):
        import time
        ms = measure_ms(time.perf_counter() - 0.01)
        assert isinstance(ms, int)
        assert ms >= 10
