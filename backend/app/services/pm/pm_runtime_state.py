"""PM Agent 运行时状态集中管理。

原状态散落为 pm_agent.py 模块级全局变量（_pm_agent_task/_last_scan_at/
_consecutive_idle_rounds/_loop_crash_count 等 8 个）+ 9 处 `global` 声明，
存在三个问题：
1. 测试需对模块级名字逐个 mock，无法整体重置/注入
2. 状态访问无类型约束，拼写错误静默产生新全局
3. 函数间通过 `global` 隐式耦合，调用顺序影响状态可读性

收拢为 PMRuntimeState 单例后：
- 巡检循环、健康检查、生命周期管理统一经 runtime_state 访问
- 测试可整实例替换（pm_agent.runtime_state = PMRuntimeState()）实现状态复位
- 字段有类型注解，访问错误可被 IDE/静态检查发现

用法：
    from app.services.pm.pm_runtime_state import runtime_state
    runtime_state.last_scan_at = time.time()
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PMRuntimeState:
    """PM Agent 巡检循环的全部可变运行时状态。

    常量（SCAN_INTERVAL_SECONDS 等配置派生值）仍保留在 pm_agent.py 模块级；
    此处仅收纳"跨轮次累积、测试需重置"的可变状态。
    """

    # 全局巡检任务引用（用于 shutdown 时取消）
    pm_agent_task: asyncio.Task | None = None

    # 上次巡检时间戳（供健康检查判断循环是否存活）
    last_scan_at: float = 0.0

    # 最近一轮巡检覆盖面（项目数/章节总数）——心跳日志的数据源
    last_round_stats: dict[str, int] = field(
        default_factory=lambda: {'scanned_projects': 0, 'scanned_chapters': 0}
    )

    # 上一轮巡检触发只读降级的项目数（供 get_pm_health 暴露）
    last_round_degraded_count: int = 0

    # 巡检循环异常计数（用于自动重启决策）
    loop_crash_count: int = 0

    # 连续无 issue 的空闲轮数（用于自动降频）
    consecutive_idle_rounds: int = 0

    # 上一轮各项目的章节数（用于检测是否有新章节）
    last_round_chapter_counts: dict[str, int] = field(default_factory=dict)

    # 每项目上次 daily_summary 时间（24h 节流，避免每日汇总刷屏）
    last_daily_summary: dict[str, datetime] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """供 get_pm_health / status API 序列化。"""
        return {
            'last_scan_at': self.last_scan_at,
            'last_round_stats': dict(self.last_round_stats),
            'last_round_degraded_count': self.last_round_degraded_count,
            'loop_crash_count': self.loop_crash_count,
            'consecutive_idle_rounds': self.consecutive_idle_rounds,
            'last_round_chapter_counts': dict(self.last_round_chapter_counts),
        }


# 模块级单例：pm_agent.py 通过本名字引用，测试可整体替换实现状态复位
runtime_state = PMRuntimeState()
