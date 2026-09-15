"""对话历史管理（内存实现）。

以 session_id 为 key，维护每个会话的：
    - 消息历史（messages）—— 格式与 OpenAI 一致：
        {"role": "user" | "assistant", "content": "..."}
    - 槽位（slots）—— 会话级键值对，用于记住订单号等已抽取的业务信息，
      例如 {"order_no": "202609030002"}。

适用于单进程 / 开发阶段；后续可替换为 Redis 或数据库实现。
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict

# 每个会话最多保留的消息条数（超出后丢弃最早的）
DEFAULT_MAX_MESSAGES = 20
# 最多保留的会话数（超出后按 LRU 淘汰最久未使用的会话）
DEFAULT_MAX_SESSIONS = 1000

VALID_ROLES = ("system", "user", "assistant")


class DialogueManager:
    """会话历史管理器（线程安全）。

    :param max_messages: 单会话最大消息数
    :param max_sessions: 最大会话数
    """

    def __init__(
        self,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        self._max_messages = max_messages
        self._max_sessions = max_sessions
        # OrderedDict 兼顾 LRU：末尾为最近使用
        self._sessions: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
        # 会话级槽位：session_id -> {slot_key: value}
        self._slots: OrderedDict[str, dict[str, str]] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 会话 id
    # ------------------------------------------------------------------
    @staticmethod
    def new_session_id() -> str:
        """生成一个新的会话 id。"""
        return uuid.uuid4().hex

    # ------------------------------------------------------------------
    # 写操作
    # ------------------------------------------------------------------
    def add_message(self, session_id: str, role: str, content: str) -> list[dict[str, str]]:
        """向指定会话追加一条消息。

        :param session_id: 会话 id，不存在则自动创建
        :param role: user / assistant / system
        :param content: 消息内容
        :return: 追加后的会话历史（副本）
        """
        if role not in VALID_ROLES:
            raise ValueError(f"非法的消息角色: {role}")

        with self._lock:
            history = self._sessions.get(session_id)
            if history is None:
                history = []
                self._sessions[session_id] = history

            history.append({"role": role, "content": content})

            # 裁剪：仅保留最近 max_messages 条
            if len(history) > self._max_messages:
                del history[: len(history) - self._max_messages]

            # 标记为最近使用
            self._sessions.move_to_end(session_id)

            # 淘汰最久未使用的会话
            while len(self._sessions) > self._max_sessions:
                old_id, _ = self._sessions.popitem(last=False)
                self._slots.pop(old_id, None)

            return list(history)

    def add_user_message(self, session_id: str, content: str) -> list[dict[str, str]]:
        """追加用户消息。"""
        return self.add_message(session_id, "user", content)

    def add_assistant_message(self, session_id: str, content: str) -> list[dict[str, str]]:
        """追加助手消息。"""
        return self.add_message(session_id, "assistant", content)

    # ------------------------------------------------------------------
    # 读 / 管理
    # ------------------------------------------------------------------
    def get_history(self, session_id: str) -> list[dict[str, str]]:
        """获取会话历史（返回副本，避免外部修改内部状态）。"""
        with self._lock:
            if session_id not in self._sessions:
                return []
            self._sessions.move_to_end(session_id)  # 访问也算一次使用
            return list(self._sessions[session_id])

    def clear_history(self, session_id: str) -> bool:
        """清空指定会话的历史（会话本身保留为空）。

        :return: 是否存在并被清空
        """
        with self._lock:
            if session_id not in self._sessions:
                return False
            self._sessions[session_id] = []
            return True

    def delete_session(self, session_id: str) -> bool:
        """彻底删除某个会话（含其槽位）。

        :return: 是否删除成功
        """
        with self._lock:
            self._slots.pop(session_id, None)
            return self._sessions.pop(session_id, None) is not None

    def session_exists(self, session_id: str) -> bool:
        """判断会话是否存在。"""
        with self._lock:
            return session_id in self._sessions

    def list_sessions(self) -> list[str]:
        """列出所有会话 id（按最近使用顺序）。"""
        with self._lock:
            return list(self._sessions.keys())

    def message_count(self, session_id: str) -> int:
        """返回指定会话的消息条数。"""
        with self._lock:
            return len(self._sessions.get(session_id, []))

    # ------------------------------------------------------------------
    # 槽位（slots）：记住订单号等已抽取信息
    # ------------------------------------------------------------------
    def set_slot(self, session_id: str, key: str, value: str) -> None:
        """写入一个会话槽位。"""
        with self._lock:
            self._slots.setdefault(session_id, {})[key] = value
            self._slots.move_to_end(session_id)

    def get_slot(self, session_id: str, key: str, default: str | None = None) -> str | None:
        """读取一个会话槽位。"""
        with self._lock:
            return self._slots.get(session_id, {}).get(key, default)

    def get_slots(self, session_id: str) -> dict[str, str]:
        """读取会话全部槽位（副本）。"""
        with self._lock:
            return dict(self._slots.get(session_id, {}))

    def clear_slots(self, session_id: str) -> None:
        """清空会话槽位。"""
        with self._lock:
            self._slots.pop(session_id, None)

    def clear_all(self) -> None:
        """清空所有会话与槽位（谨慎使用，主要供测试）。"""
        with self._lock:
            self._sessions.clear()
            self._slots.clear()

    # ------------------------------------------------------------------
    # 重启恢复：从 LogStore 回填最近活跃会话
    # ------------------------------------------------------------------
    def restore_session(self, session_id: str, messages: list[dict[str, str]]) -> int:
        """把来自 LogStore 的历史灌回内存（保留最近 max_messages 条）。

        :return: 实际写入的消息条数
        """
        if not session_id or not messages:
            return 0
        # 仅保留合法 role + 非空 content
        filtered = [
            m for m in messages
            if isinstance(m, dict)
            and m.get("role") in VALID_ROLES
            and m.get("content")
        ]
        if not filtered:
            return 0
        with self._lock:
            history = filtered[-self._max_messages:]
            self._sessions[session_id] = list(history)
            self._sessions.move_to_end(session_id)
        return len(history)

    def restore_session_summary(self, session_id: str, slots: dict[str, str]) -> None:
        """恢复会话槽位（一般从 LogStore 摘要得到）。"""
        if not session_id or not slots:
            return
        with self._lock:
            self._slots[session_id] = dict(slots)
            self._slots.move_to_end(session_id)

    # ------------------------------------------------------------------
    # 多轮上下文压缩
    # ------------------------------------------------------------------
    def mark_summarized(self, session_id: str) -> None:
        """标记该会话已完成一次摘要（防止反复触发）。"""
        with self._lock:
            # 用 _slots 空间记录 _summarized 标记
            slots = self._slots.setdefault(session_id, {})
            slots["_summarized"] = "1"

    def has_been_summarized(self, session_id: str) -> bool:
        """该会话是否已摘要过。"""
        with self._lock:
            return self._slots.get(session_id, {}).get("_summarized") == "1"


# 模块级单例
dialogue_manager = DialogueManager()
