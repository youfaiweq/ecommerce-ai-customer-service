"""P1 改进测试：SQLite PRAGMA、限流正则、Admin 多 key、FAQ 热更新、会话导出。"""

from __future__ import annotations

import json


# ===========================================================================
# SQLite PRAGMA
# ===========================================================================
class TestSqlitePragma:
    def test_wal_mode_enabled(self, tmp_path):
        from app.services.log_store import LogStore

        s = LogStore(db_path=tmp_path / "p.db")
        s.init_db()
        with s._connect() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_synchronous_normal(self, tmp_path):
        from app.services.log_store import LogStore

        s = LogStore(db_path=tmp_path / "p.db")
        s.init_db()
        with s._connect() as conn:
            level = conn.execute("PRAGMA synchronous").fetchone()[0]
        assert level == 1  # NORMAL = 1, FULL = 2

    def test_temp_store_memory(self, tmp_path):
        from app.services.log_store import LogStore

        s = LogStore(db_path=tmp_path / "p.db")
        s.init_db()
        with s._connect() as conn:
            v = conn.execute("PRAGMA temp_store").fetchone()[0]
        assert v == 2  # MEMORY = 2

    def test_mmap_size_set(self, tmp_path):
        from app.services.log_store import LogStore

        s = LogStore(db_path=tmp_path / "p.db")
        s.init_db()
        with s._connect() as conn:
            size = conn.execute("PRAGMA mmap_size").fetchone()[0]
        assert size >= 256 * 1024 * 1024  # 256MB


# ===========================================================================
# 限流：正则豁免
# ===========================================================================
class TestRateLimitExempt:
    def test_health_exact_match(self):
        from app.utils.rate_limit import _compile_exempt_patterns

        pats = _compile_exempt_patterns(["/health"])
        assert any(p.match("/health") for p in pats)
        assert any(p.match("/health/deep") for p in pats)
        # 关键回归：不应当误匹配 /healthcheck
        assert not any(p.match("/healthcheck") for p in pats)
        assert not any(p.match("/health-anything") for p in pats)

    def test_docs_match(self):
        from app.utils.rate_limit import _compile_exempt_patterns

        pats = _compile_exempt_patterns(["/docs", "/openapi.json"])
        assert any(p.match("/docs") for p in pats)
        assert any(p.match("/docs/foo") for p in pats)
        assert not any(p.match("/docss") for p in pats)
        assert any(p.match("/openapi.json") for p in pats)
        # openapi.json 是文件，不应当再匹配 openapi.jsonx
        assert not any(p.match("/openapi.jsonx") for p in pats)

    def test_admin_not_exempt_by_default(self):
        """配置里没列 /admin，默认应当受限流影响。"""
        from app.utils.rate_limit import _compile_exempt_patterns

        pats = _compile_exempt_patterns(["/health", "/docs", "/ui"])
        assert not any(p.match("/admin/sessions") for p in pats)


# ===========================================================================
# Admin 多 Key
# ===========================================================================
class TestAdminKeys:
    def test_single_key(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "admin_api_key", "abc", raising=False)
        monkeypatch.setattr(settings, "admin_api_keys", "", raising=False)
        assert "abc" in settings.admin_keys

    def test_multi_keys(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "admin_api_key", "", raising=False)
        monkeypatch.setattr(settings, "admin_api_keys", "k1,k2, k3", raising=False)
        keys = settings.admin_keys
        assert {"k1", "k2", "k3"} == keys

    def test_mixed_dedup(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "admin_api_key", "k1", raising=False)
        monkeypatch.setattr(settings, "admin_api_keys", "k1,k2", raising=False)
        assert settings.admin_keys == {"k1", "k2"}

    def test_admin_enabled_flag(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "admin_api_key", "", raising=False)
        monkeypatch.setattr(settings, "admin_api_keys", "", raising=False)
        assert settings.admin_enabled is False
        monkeypatch.setattr(settings, "admin_api_keys", "x", raising=False)
        assert settings.admin_enabled is True

    def test_admin_endpoint_with_multi_keys(self, client, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "admin_api_key", "", raising=False)
        monkeypatch.setattr(settings, "admin_api_keys", "k1,k2", raising=False)
        # 任一 key 通过
        resp = client.get("/admin/stats", headers={"X-Admin-Key": "k2"})
        assert resp.status_code == 200
        # 错误 key 拒绝
        resp = client.get("/admin/stats", headers={"X-Admin-Key": "wrong"})
        assert resp.status_code == 401


# ===========================================================================
# FAQ 热更新
# ===========================================================================
class TestKnowledgeReload:
    def test_reload_endpoint(self, client, tmp_path, monkeypatch):
        """先改 faq.json，调用 reload 接口，验证索引被重建。"""
        import shutil

        from app.config import settings
        from app.services.knowledge_base import knowledge_base

        # 拷贝 faq.json 到 tmp_path 并修改条数
        src = settings.data_path / "faq.json"
        dst = tmp_path / "faq.json"
        shutil.copy(src, dst)
        new_data = [
            {"id": "test_001", "category": "测试", "question": "测试问题", "answer": "测试回答", "keywords": ["test"]}
        ]
        dst.write_text(json.dumps(new_data, ensure_ascii=False), encoding="utf-8")
        # 把 data_path 临时指向 tmp_path
        monkeypatch.setattr(settings, "data_dir", str(tmp_path))
        # 清缓存（lru_cache）
        from app.utils.data_loader import load_faqs

        load_faqs.cache_clear()
        # 验证 reload 前是原数量
        assert knowledge_base.size != len(new_data)

        resp = client.post("/knowledge/reload", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["reloaded"] is True
        assert body["faq_count"] == 1
        assert body["backend"]
        # 索引已被重建
        assert knowledge_base.size == 1

    def test_reload_invalid_json(self, client, tmp_path, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "data_dir", str(tmp_path))
        bad = tmp_path / "faq.json"
        bad.write_text("{not json", encoding="utf-8")
        from app.utils.data_loader import load_faqs

        load_faqs.cache_clear()

        resp = client.post("/knowledge/reload", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 400

    def test_stats_includes_mtime(self, client):
        resp = client.get("/knowledge/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "faq_count" in body
        assert "backend" in body
        assert "faq_path" in body
        assert "faq_exists" in body


# ===========================================================================
# 会话导出
# ===========================================================================
class TestSessionExport:
    def test_export_markdown(self, client):
        from app.services.log_store import log_store

        log_store.record_message("sess-export-1", "user", "你好", {"intent": "other"})
        log_store.record_message(
            "sess-export-1",
            "assistant",
            "您好，有什么可以帮您？",
            {"intent": "other", "grounded": True, "transferred": False},
        )
        resp = client.get("/admin/sessions/sess-export-1/export?format=md")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        text = resp.text
        assert "sess-export-1" in text
        assert "你好" in text
        assert "您好" in text
        # Content-Disposition 应有 attachment
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_export_json(self, client):
        from app.services.log_store import log_store

        log_store.record_message("sess-export-2", "user", "test", {"intent": "other"})
        resp = client.get("/admin/sessions/sess-export-2/export?format=json")
        assert resp.status_code == 200
        body = json.loads(resp.text)
        assert body["session"]["session_id"] == "sess-export-2"
        assert len(body["messages"]) == 1
        assert "exported_at" in body

    def test_export_invalid_format(self, client):
        resp = client.get("/admin/sessions/x/export?format=xml")
        assert resp.status_code == 422  # FastAPI 校验失败

    def test_export_nonexistent_session(self, client):
        resp = client.get("/admin/sessions/nonexistent-session-id/export?format=md")
        assert resp.status_code == 404

    def test_export_requires_admin_key_when_enabled(self, client, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "admin_api_key", "secret", raising=False)
        monkeypatch.setattr(settings, "admin_api_keys", "", raising=False)
        # 没带 key → 401
        resp = client.get("/admin/sessions/x/export")
        assert resp.status_code == 401
        # 带 key 通过
        from app.services.log_store import log_store

        log_store.record_message("sess-ok", "user", "hi", {"intent": "other"})
        resp = client.get(
            "/admin/sessions/sess-ok/export?format=md",
            headers={"X-Admin-Key": "secret"},
        )
        assert resp.status_code == 200
