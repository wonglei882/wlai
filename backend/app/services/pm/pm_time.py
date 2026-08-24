"""PM 模块统一时间工具。

T0.2 优化：消除 PM 范围内 `datetime.now()` 与 `datetime.utcnow()` 混用导致的
8 小时时区偏差（冷却窗口、token 日统计等判断受影响）。

策略：
- PM 模块内**所有代码**统一 `pm_now()`（本地 now，与各模型默认值 `datetime.now()` 对齐）
- 禁止 PM 模块直接写 `datetime.utcnow()` / `datetime.now()`
- `server_default=func.now()`（DB 端）与 Python 端 `pm_now()` 保持一致（都取本地）
"""

from __future__ import annotations

from datetime import datetime
from collections.abc import Callable


# 允许测试场景下注入替换时钟
_now_fn: Callable[[], datetime] = datetime.now


def set_pm_now_fn(fn: Callable[[], datetime]) -> None:
    """测试专用：注入自定义 now 函数（可模拟时间流逝）。"""
    global _now_fn
    _now_fn = fn


def reset_pm_now_fn() -> None:
    """测试专用：恢复真实 now 函数。"""
    global _now_fn
    _now_fn = datetime.now


def pm_now() -> datetime:
    """返回 PM 模块统一使用的当前时间（= datetime.now()）。

    设计：
    - 与数据库模型 Column(default=datetime.now) 保持一致
    - 模型 `created_at` / `updated_at` / `feedback_at` 统一取同一时钟基准
    - 冷却窗口、token 日统计、approved 7 天窗口都不会出现时区偏差
    """
    return _now_fn()
