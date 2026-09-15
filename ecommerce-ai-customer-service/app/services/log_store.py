"""会话日志存储（SQLite）。

把每轮对话持久化到本地 SQLite，便于：
    - 事后排查问题、复盘对话
    - 通过管理接口（``/admin``）查看历史会话
    - 统计意图分布、转人工次数等
    - 服务重启时回填对话历史

设计要点：
    - 仅用标准库 ``sqlite3``，零额外依赖
    - 每次写操作独立建立连接（线程安全、无需连接池），启用 WAL 提升并发读性能
    - 写入走 ``asyncio.Queue`` 后台 worker，不阻塞请求路径
    - 通过 ``settings.log_store_enabled`` 可整体关闭；关闭后所有方法安全空转
    - 单条消息的附加信息（引用来源等）以 JSON 文本存储，保持表结构简单
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.redact import redact_text

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    message_count     INTEGER NOT NULL DEFAULT 0,
    last_intent       TEXT,
    transferred_count INTEGER NOT NULL DEFAULT 0,
    user_id           TEXT,
    session_secret_hash TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    intent      TEXT,
    sources     TEXT,
    order_no    TEXT,
    order_found INTEGER,
    grounded    INTEGER,
    transferred INTEGER,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    message_id  INTEGER,
    score       INTEGER NOT NULL,        -- 1=👍  -1=👎
    comment     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti        TEXT PRIMARY KEY,
    expires_at REAL NOT NULL,
    revoked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_session ON feedback(session_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expiry ON revoked_tokens(expires_at);
"""

# 增量迁移：给存量 sessions 表补 user_id 列（CREATE IF NOT EXISTS 不会改既有表）
_MIGRATIONS = [
    "ALTER TABLE sessions ADD COLUMN user_id TEXT",
    "ALTER TABLE sessions ADD COLUMN session_secret_hash TEXT",
]


def _now() -> str:
    """当前时间（UTC，秒级 ISO8601）。"""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _as_int(value: Any) -> int | None:
    """布尔 / 数字转 0-1；None 保持 None。"""
    if value is None:
        return None
    return 1 if value else 0


class LogStore:
    """会话日志存储（含异步写入队列 + 重启恢复接口）。"""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else settings.log_db_file
        self._lock = threading.Lock()
        self._ready = False
        # 异步队列：worker 异步消费
        self._queue: asyncio.Queue[dict] | None = None
        self._worker_task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        # worker 批大小 / 间隔（毫秒）
        self._flush_batch = settings.log_store_batch_size
        self._flush_interval_ms = settings.log_store_flush_interval_ms

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(settings.log_store_enabled)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        # PRAGMA 调优（顺序敏感）
        # journal_mode=WAL: 读写并发不互斥
        conn.execute("PRAGMA journal_mode=WAL")
        # synchronous=NORMAL: WAL 模式下 NORMAL 足够安全（崩溃可能丢最后一两个事务，但
        #   不会丢整个数据库）；FULL 比 NORMAL 慢约 2-3 倍
        conn.execute("PRAGMA synchronous=NORMAL")
        # temp_store=MEMORY: 临时表/索引放内存
        conn.execute("PRAGMA temp_store=MEMORY")
        # mmap_size=256MB: 大数据量读取走内存映射
        conn.execute("PRAGMA mmap_size=268435456")  # 256 * 1024 * 1024
        # cache_size=-64000: ~64MB 页缓存（负数单位为 KB）
        conn.execute("PRAGMA cache_size=-64000")
        # foreign_keys=ON: 保留原约束（即便当前 schema 没用到外键）
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_db(self) -> bool:
        if not self.enabled:
            logger.info("会话日志存储已关闭（LOG_STORE_ENABLED=false）")
            return False
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self._connect() as conn:
                conn.executescript(_SCHEMA)
                # 兼容存量 DB：尝试增量迁移，已存在该列时忽略 "duplicate column" 错误
                for stmt in _MIGRATIONS:
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError as e:
                        # "duplicate column name: user_id" 是预期内的（已迁移过）
                        if "duplicate column" not in str(e).lower():
                            raise
            self._ready = True
            logger.info("会话日志库就绪：%s", self._db_path)
            return True
        except Exception as exc:
            logger.warning("初始化会话日志库失败（将降级为不落库）：%s", exc)
            self._ready = False
            return False

    # ------------------------------------------------------------------
    # 异步写入队列
    # ------------------------------------------------------------------
    async def startup(self) -> None:
        """lifespan 阶段调用：初始化 DB + 启动后台 flush worker。"""
        self.init_db()
        if not self._ready:
            return
        if self._queue is None:
            self._queue = asyncio.Queue()
        if self._stop_event is None:
            self._stop_event = asyncio.Event()
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._flush_worker(), name="log-flush-worker")
            logger.info("LogStore 后台 flush worker 已启动")

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        """lifespan 关闭：通知 worker + 排空队列。

        :param timeout: 等待 worker 退出的最大秒数
        """
        if self._stop_event is not None:
            self._stop_event.set()
        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._worker_task, timeout=timeout)
            except (TimeoutError, asyncio.CancelledError):
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                logger.warning("LogStore worker 未在 %ss 内退出，已强制取消", timeout)
        # 关闭前再 flush 一次（兜底：worker 退出后剩余在队列里的）
        if self._queue is not None and not self._queue.empty():
            await self._flush_once()

    async def _flush_worker(self) -> None:
        assert self._queue is not None and self._stop_event is not None
        while True:
            try:
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=self._flush_interval_ms / 1000
                )
                batch = [item]
                # 凑批
                while len(batch) < self._flush_batch:
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                self._record_batch(batch)
            except TimeoutError:
                if self._stop_event.is_set():
                    break
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("LogStore worker 异常：%s", exc)

    async def _flush_once(self) -> None:
        if self._queue is None or self._queue.empty():
            return
        batch: list[dict] = []
        while not self._queue.empty() and len(batch) < 1000:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            self._record_batch(batch)

    def _record_batch(self, items: list[dict]) -> None:
        """同步批量写：单次事务 → 显著降低 fsync 次数。"""
        if not self._ready or not items:
            return
        now = _now()
        rows = []
        for it in items:
            content = it.get("content", "")
            if settings.redact_pii:
                content = redact_text(content)
            meta = it.get("meta") or {}
            sources = meta.get("sources")
            sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
            rows.append((
                it["session_id"], it["role"], content,
                meta.get("intent"), sources_json, meta.get("order_no"),
                _as_int(meta.get("order_found")), _as_int(meta.get("grounded")),
                _as_int(meta.get("transferred")),
                now,
            ))
        try:
            with self._lock, self._connect() as conn:
                # upsert sessions
                for sid in {r[0] for r in rows}:
                    conn.execute(
                        """
                        INSERT INTO sessions (session_id, created_at, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
                        """,
                        (sid, now, now),
                    )
                # insert messages
                conn.executemany(
                    """
                    INSERT INTO messages
                        (session_id, role, content, intent, sources, order_no,
                         order_found, grounded, transferred, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                # update aggregates per session
                from collections import Counter
                per_session = Counter()
                per_transferred = Counter()
                per_intent = {}
                for sid, _role, _content, intent, _src, _ono, _of, _gr, transferred, _t in rows:
                    per_session[sid] += 1
                    if transferred == 1:
                        per_transferred[sid] += 1
                    if intent and sid not in per_intent:
                        per_intent[sid] = intent
                for sid, cnt in per_session.items():
                    conn.execute(
                        """
                        UPDATE sessions
                           SET message_count     = message_count + ?,
                               updated_at        = ?,
                               last_intent       = COALESCE(?, last_intent),
                               transferred_count = transferred_count + ?
                         WHERE session_id = ?
                        """,
                        (cnt, now, per_intent.get(sid), per_transferred.get(sid, 0), sid),
                    )
                conn.commit()
        except Exception as exc:
            logger.warning("批量写入会话日志失败（已忽略）：%s", exc)

    def enqueue_message(
        self,
        session_id: str,
        role: str,
        content: str,
        meta: dict | None = None,
    ) -> None:
        """异步入队（不阻塞请求路径）。

        若 worker 尚未启动（lifespan 未跑），则降级为同步写入，保证不丢消息。
        """
        item = {"session_id": session_id, "role": role, "content": content, "meta": meta or {}}
        if not self.enabled or not self._ready:
            return
        if self._queue is not None:
            try:
                self._queue.put_nowait(item)
                return
            except asyncio.QueueFull:
                logger.warning("LogStore 队列已满，降级同步写入")
        # 降级：同步写
        self.record_message(session_id, role, content, meta)

    # ------------------------------------------------------------------
    # 同步写入（保留兼容 + 给 worker 降级路径用）
    # ------------------------------------------------------------------
    def record_message(
        self,
        session_id: str,
        role: str,
        content: str,
        meta: dict | None = None,
    ) -> None:
        if not self.enabled or not self._ready:
            return
        meta = meta or {}
        if settings.redact_pii:
            content = redact_text(content)
        sources = meta.get("sources")
        sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
        intent = meta.get("intent")
        order_no = meta.get("order_no")
        order_found = _as_int(meta.get("order_found"))
        grounded = _as_int(meta.get("grounded"))
        transferred = _as_int(meta.get("transferred"))
        now = _now()
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, created_at, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
                    """,
                    (session_id, now, now),
                )
                conn.execute(
                    """
                    INSERT INTO messages
                        (session_id, role, content, intent, sources, order_no,
                         order_found, grounded, transferred, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id, role, content, intent, sources_json, order_no,
                        order_found, grounded, transferred, now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE sessions
                       SET message_count     = message_count + 1,
                           updated_at        = ?,
                           last_intent       = COALESCE(?, last_intent),
                           transferred_count = transferred_count + ?
                     WHERE session_id = ?
                    """,
                    (now, intent, 1 if transferred == 1 else 0, session_id),
                )
        except Exception as exc:
            logger.warning("写入会话日志失败（已忽略）：%s", exc)

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def list_sessions(self, limit: int = 20, offset: int = 0) -> list[dict]:
        if not self.enabled or not self._ready:
            return []
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM sessions
                     ORDER BY updated_at DESC
                     LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("读取会话列表失败：%s", exc)
            return []

    def list_active_sessions(self, since_seconds: int = 7 * 24 * 3600,
                              limit: int = 200) -> list[str]:
        """列出最近活跃的 session_id，供启动时回填用。"""
        if not self.enabled or not self._ready:
            return []
        try:
            since_iso = (
                datetime.now(UTC).timestamp() - since_seconds
            )
            from datetime import datetime as _dt
            cutoff = _dt.fromtimestamp(since_iso, tz=UTC).isoformat(timespec="seconds")
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT session_id FROM sessions
                     WHERE updated_at >= ?
                     ORDER BY updated_at DESC
                     LIMIT ?
                    """,
                    (cutoff, limit),
                ).fetchall()
            return [r["session_id"] for r in rows]
        except Exception as exc:
            logger.warning("列出活跃会话失败：%s", exc)
            return []

    def get_session(self, session_id: str) -> dict | None:
        if not self.enabled or not self._ready:
            return None
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
            return dict(row) if row else None
        except Exception as exc:
            logger.warning("读取会话失败：%s", exc)
            return None

    # ------------------------------------------------------------------
    # 会话归属用户（鉴权接入后绑定）
    # ------------------------------------------------------------------
    def set_session_user(self, session_id: str, user_id: str | None) -> bool:
        """绑定会话归属用户；未登录（user_id=None）则跳过。

        采用 upsert：会话不存在则创建，存在则更新 user_id（保留已有 user_id）。
        """
        if not self.enabled or not self._ready or not user_id:
            return False
        now = _now()
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, created_at, updated_at, user_id)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        user_id = COALESCE(sessions.user_id, excluded.user_id)
                    """,
                    (session_id, now, now, str(user_id)),
                )
            return True
        except Exception as exc:
            logger.warning("绑定会话归属用户失败：%s", exc)
            return False

    def get_session_owner(self, session_id: str) -> str | None:
        """查询会话归属用户；不存在或未登录时返回 None。"""
        if not self.enabled or not self._ready:
            return None
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT user_id FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            return row["user_id"] if row else None
        except Exception as exc:
            logger.warning("查询会话归属用户失败：%s", exc)
            return None

    def set_session_secret_hash(self, session_id: str, secret_hash: str) -> bool:
        """保存匿名会话凭证的摘要，永不写入原始凭证。"""
        if not self.enabled or not self._ready or not session_id or not secret_hash:
            return False
        now = _now()
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, created_at, updated_at, session_secret_hash)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        session_secret_hash = COALESCE(
                            sessions.session_secret_hash, excluded.session_secret_hash
                        )
                    """,
                    (session_id, now, now, secret_hash),
                )
            return True
        except Exception as exc:
            logger.warning("保存匿名会话凭证摘要失败：%s", exc)
            return False

    def get_session_secret_hash(self, session_id: str) -> str | None:
        """读取匿名会话凭证摘要；仅用于恒定时间校验。"""
        if not self.enabled or not self._ready:
            return None
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT session_secret_hash FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
            return row["session_secret_hash"] if row else None
        except Exception as exc:
            logger.warning("读取匿名会话凭证摘要失败：%s", exc)
            return None

    def revoke_token(self, jti: str, expires_at: float) -> bool:
        """记录已登出的 token JTI，直到其自然过期。"""
        if not self.enabled or not self._ready or not jti:
            return False
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO revoked_tokens (jti, expires_at, revoked_at) VALUES (?, ?, ?)",
                    (jti, float(expires_at), _now()),
                )
                conn.execute("DELETE FROM revoked_tokens WHERE expires_at <= ?", (datetime.now(UTC).timestamp(),))
            return True
        except Exception as exc:
            logger.warning("撤销 token 失败：%s", exc)
            return False

    def is_token_revoked(self, jti: str) -> bool:
        """检查 token 是否在撤销表中；存储不可用时保持验证失败安全由调用方处理。"""
        if not self.enabled or not self._ready or not jti:
            return False
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM revoked_tokens WHERE jti = ? AND expires_at > ?",
                    (jti, datetime.now(UTC).timestamp()),
                ).fetchone()
            return row is not None
        except Exception as exc:
            logger.warning("查询 token 撤销状态失败：%s", exc)
            return False

    def get_messages(self, session_id: str, limit: int = 200, offset: int = 0) -> list[dict]:
        if not self.enabled or not self._ready:
            return []
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM messages
                     WHERE session_id = ?
                     ORDER BY id ASC
                     LIMIT ? OFFSET ?
                    """,
                    (session_id, limit, offset),
                ).fetchall()
        except Exception as exc:
            logger.warning("读取会话消息失败：%s", exc)
            return []

        result = []
        for row in rows:
            item = dict(row)
            if item.get("sources"):
                try:
                    item["sources"] = json.loads(item["sources"])
                except (TypeError, ValueError):
                    item["sources"] = []
            for key in ("order_found", "grounded", "transferred"):
                if item.get(key) is not None:
                    item[key] = bool(item[key])
            result.append(item)
        return result

    def search_messages(self, keyword: str, limit: int = 50) -> list[dict]:
        if not self.enabled or not self._ready or not keyword.strip():
            return []
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, session_id, role, content, created_at
                      FROM messages
                     WHERE content LIKE ?
                     ORDER BY id DESC
                     LIMIT ?
                    """,
                    (f"%{keyword.strip()}%", limit),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("搜索消息失败：%s", exc)
            return []

    # ------------------------------------------------------------------
    # 统计 / 删除
    # ------------------------------------------------------------------
    def stats(self) -> dict:
        empty = {
            "total_sessions": 0,
            "total_messages": 0,
            "transferred_sessions": 0,
            "intent_distribution": {},
            "feedback_total": 0,
            "feedback_positive": 0,
            "feedback_negative": 0,
        }
        if not self.enabled or not self._ready:
            return empty
        try:
            with self._lock, self._connect() as conn:
                total_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                transferred = conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE transferred_count > 0"
                ).fetchone()[0]
                intent_rows = conn.execute(
                    """
                    SELECT intent, COUNT(*) AS cnt
                      FROM messages
                     WHERE intent IS NOT NULL AND role = 'user'
                     GROUP BY intent
                     ORDER BY cnt DESC
                    """
                ).fetchall()
                fb_row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN score = 1 THEN 1 ELSE 0 END) AS positive,
                        SUM(CASE WHEN score = -1 THEN 1 ELSE 0 END) AS negative
                      FROM feedback
                    """
                ).fetchone()
            return {
                "total_sessions": total_sessions,
                "total_messages": total_messages,
                "transferred_sessions": transferred,
                "intent_distribution": {r["intent"]: r["cnt"] for r in intent_rows},
                "feedback_total": fb_row["total"] or 0,
                "feedback_positive": fb_row["positive"] or 0,
                "feedback_negative": fb_row["negative"] or 0,
            }
        except Exception as exc:
            logger.warning("统计失败：%s", exc)
            return empty

    def delete_session(self, session_id: str) -> bool:
        if not self.enabled or not self._ready:
            return False
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM sessions WHERE session_id = ?", (session_id,)
                )
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM feedback WHERE session_id = ?", (session_id,))
                return cur.rowcount > 0
        except Exception as exc:
            logger.warning("删除会话失败：%s", exc)
            return False

    # ------------------------------------------------------------------
    # 用户反馈（👍 / 👎）
    # ------------------------------------------------------------------
    def record_feedback(
        self,
        session_id: str,
        score: int,
        message_id: int | None = None,
        comment: str | None = None,
    ) -> bool:
        """记录一条反馈。

        :param session_id: 会话 id
        :param score: 1（👍）或 -1（👎）
        :param message_id: 可选，关联 messages.id
        :param comment: 可选评论
        :return: 是否写入成功
        """
        if not self.enabled or not self._ready:
            return False
        if score not in (1, -1):
            return False
        now = _now()
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO feedback
                        (session_id, message_id, score, comment, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, message_id, score, comment, now),
                )
            return True
        except Exception as exc:
            logger.warning("写入反馈失败：%s", exc)
            return False

    def get_feedback_for_session(self, session_id: str) -> list[dict]:
        """获取某会话的全部反馈记录。"""
        if not self.enabled or not self._ready:
            return []
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM feedback
                     WHERE session_id = ?
                     ORDER BY id ASC
                    """,
                    (session_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("读取反馈失败：%s", exc)
            return []

    def feedback_stats(self) -> dict:
        """汇总：总 👍 / 总 👎 / 好评率 / 最近 N 条。"""
        empty = {
            "total": 0,
            "positive": 0,
            "negative": 0,
            "positive_rate": 0.0,
            "with_comment": 0,
            "by_session": [],
            "recent": [],
        }
        if not self.enabled or not self._ready:
            return empty
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN score = 1 THEN 1 ELSE 0 END) AS positive,
                        SUM(CASE WHEN score = -1 THEN 1 ELSE 0 END) AS negative,
                        SUM(CASE WHEN comment IS NOT NULL AND comment != '' THEN 1 ELSE 0 END) AS with_comment
                      FROM feedback
                    """
                ).fetchone()
                by_session = conn.execute(
                    """
                    SELECT session_id,
                           SUM(CASE WHEN score = 1 THEN 1 ELSE 0 END) AS positive,
                           SUM(CASE WHEN score = -1 THEN 1 ELSE 0 END) AS negative,
                           COUNT(*) AS total
                      FROM feedback
                     GROUP BY session_id
                     ORDER BY MAX(id) DESC
                     LIMIT 50
                    """
                ).fetchall()
                recent = conn.execute(
                    """
                    SELECT id, session_id, message_id, score, comment, created_at
                      FROM feedback
                     ORDER BY id DESC
                     LIMIT 20
                    """
                ).fetchall()
            total = rows["total"] or 0
            positive = rows["positive"] or 0
            negative = rows["negative"] or 0
            positive_rate = (positive / total) if total else 0.0
            return {
                "total": total,
                "positive": positive,
                "negative": negative,
                "positive_rate": round(positive_rate, 4),
                "with_comment": rows["with_comment"] or 0,
                "by_session": [dict(r) for r in by_session],
                "recent": [dict(r) for r in recent],
            }
        except Exception as exc:
            logger.warning("统计反馈失败：%s", exc)
            return empty


# 模块级单例
log_store = LogStore()
