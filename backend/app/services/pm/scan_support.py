"""PM 扫描支撑模块 — 扫描器上游查库辅助 + 纯函数过滤逻辑。

职责边界：
- 只承载「扫描产出前」的辅助查询与纯函数过滤，不做诊断写入、不做修复决策。
- 供 pm_scanners.py / pm_consistency_guardian.py 复用；不依赖任何 pm 服务模块（避免循环导入）。

背景（生产实证）：
1. outline_drift 正则裸抽取的汉字碎片（如「化肥到货」）被当角色名对比 →
   候选名必须命中 characters 表白名单才参与对比（filter_names_by_whitelist）。
2. world_rule_drift 同一漂移重复入账 72 次：_upsert_diagnostic_log 的去重窗口仅 1h，
   小于巡检间隔叠加效应 → 收敛检查必须在扫描产出侧（has_unresolved_diagnostic）。
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import logging

logger = logging.getLogger(__name__)


def filter_names_by_whitelist(candidates: Iterable[str], known_names: Iterable[str]) -> set[str]:
    """按项目注册角色白名单过滤候选名。

    匹配规则（满足其一即保留候选）：
    1. 精确命中：candidate == 注册名
    2. 变体包含（超集）：candidate 包含某注册名，且该注册名长度 >= 2
       （如候选「林凡儿」包含注册名「林凡」）
    3. 变体包含（子集）：candidate 被某注册名包含，且 candidate 长度 >= 2
       （如候选「林凡」被注册名「林凡天」包含）

    Args:
        candidates: 待过滤的候选名集合（正则抽取的汉字碎片）
        known_names: 该项目 characters 表注册角色名集合

    Returns:
        通过白名单的候选名子集。known_names 为空时返回空集（空集 ≠ 漂移，
        由调用方据此跳过角色名对比）。
    """
    known = {name for name in known_names if name}
    if not known:
        return set()

    kept: set[str] = set()
    for cand in candidates:
        if not cand:
            continue
        for name in known:
            if cand == name or (len(name) >= 2 and name in cand) or (len(cand) >= 2 and cand in name):
                kept.add(cand)
                break
    return kept


async def load_character_names(db: AsyncSession, project_id: str) -> set[str]:
    """加载项目注册角色名集合（characters 表），供 outline 白名单对比使用。"""
    from app.models.character import Character

    result = await db.execute(select(Character.name).where(Character.project_id == project_id))
    return {row[0] for row in result.all() if row[0]}


async def has_unresolved_diagnostic(db: AsyncSession, project_id: str, diag_type: str) -> bool:
    """检查同 project 同 diag_type 是否存在 resolved=False 的未决诊断记录。

    用于扫描产出侧收敛去重：存在未决记录时跳过本次产出，避免同一问题
    每轮巡检重复入账（_upsert_diagnostic_log 的 1h 窗口挡不住跨轮重报）。
    """
    from app.models.pm_diagnostic_log import PMDiagnosticLog

    result = await db.execute(
        select(PMDiagnosticLog.id)
        .where(
            PMDiagnosticLog.project_id == project_id,
            PMDiagnosticLog.diag_type == diag_type,
            PMDiagnosticLog.resolved.is_(False),
        )
        .limit(1)
    )
    return result.first() is not None
