"""数据加载工具。

负责从 `data/` 目录读取 FAQ 与订单等 JSON 模拟数据，
并对读取结果做进程内缓存，避免重复 IO。

约定：
    - 数据文件位于 `settings.data_path`（默认 项目根/data）。
    - 所有 JSON 文件以 UTF-8 编码保存。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings


# 数据目录（每次读取 settings，方便测试 monkeypatch）
def _data_dir() -> Path:
    """获取当前数据目录绝对路径。"""
    return settings.data_path


class DataNotFoundError(FileNotFoundError):
    """数据文件不存在时抛出。"""


def _read_json(filename: str) -> Any:
    """读取 data/ 目录下的 JSON 文件并解析。

    :param filename: 文件名，例如 "faq.json"
    :raises DataNotFoundError: 文件不存在
    :raises json.JSONDecodeError: JSON 格式错误
    """
    path = _data_dir() / filename
    if not path.exists():
        raise DataNotFoundError(f"数据文件不存在: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# FAQ
# ============================================================
@lru_cache(maxsize=1)
def load_faqs() -> list[dict]:
    """加载全部 FAQ 数据（带缓存）。

    :return: FAQ 列表，每项含 id / category / question / answer / keywords
    """
    return _read_json("faq.json")


def list_faq_categories() -> list[str]:
    """返回所有 FAQ 分类（去重，保持出现顺序）。"""
    seen: list[str] = []
    for item in load_faqs():
        cat = item.get("category")
        if cat and cat not in seen:
            seen.append(cat)
    return seen


def search_faqs(keyword: str, category: str | None = None) -> list[dict]:
    """按关键词与分类检索 FAQ。

    匹配范围：问题、答案、关键词列表（大小写不敏感的子串匹配）。

    :param keyword: 查询关键词；为空时仅按分类过滤
    :param category: 可选，限定分类
    :return: 命中的 FAQ 列表
    """
    kw = (keyword or "").strip().lower()
    results: list[dict] = []

    for item in load_faqs():
        if category and item.get("category") != category:
            continue
        if kw:
            haystack = " ".join(
                [
                    str(item.get("question", "")),
                    str(item.get("answer", "")),
                    " ".join(item.get("keywords", []) or []),
                ]
            ).lower()
            if kw not in haystack:
                continue
        results.append(item)

    return results


# ============================================================
# 订单
# ============================================================
@lru_cache(maxsize=1)
def load_orders() -> list[dict]:
    """加载全部订单数据（带缓存）。

    :return: 订单列表
    """
    return _read_json("orders.json")


def get_order_by_no(order_no: str) -> dict | None:
    """按订单号查询单个订单。

    :param order_no: 订单号
    :return: 订单字典，未找到返回 None
    """
    target = (order_no or "").strip()
    for order in load_orders():
        if order.get("order_no") == target:
            return order
    return None


def get_orders_by_user(user_id: str) -> list[dict]:
    """查询某个用户的所有订单。"""
    return [o for o in load_orders() if o.get("user_id") == user_id]


def get_order_tracking(order_no: str) -> dict | None:
    """查询订单的物流信息。"""
    order = get_order_by_no(order_no)
    if not order:
        return None
    return order.get("logistics")


# ============================================================
# 缓存管理
# ============================================================
def reload_data() -> None:
    """清空缓存，强制下次调用重新读取文件。

    修改 data/ 下的 JSON 后调用本函数即可生效（无需重启服务）。
    """
    load_faqs.cache_clear()
    load_orders.cache_clear()


if __name__ == "__main__":
    # 手动自测：python -m app.utils.data_loader
    print(f"数据目录: {_data_dir()}")
    print(f"FAQ 条数: {len(load_faqs())}，分类: {list_faq_categories()}")
    print(f"订单条数: {len(load_orders())}")
    print("查询 202609030002 ->", get_order_by_no("202609030002")["status"])
    print("搜索『退款』命中:", [f["id"] for f in search_faqs("退款")])
