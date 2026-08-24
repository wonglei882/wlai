"""修复模式库服务 — 验证通过方案的沉淀与复用（L4 经验进化）。

- learn_fix_pattern : auto_fix 验证通过后沉淀/强化（同类型优先保留最成功者）
- find_best_pattern  : 查同类型最成功的先例
- pattern_boost      : 成功先例 → 决策评分提升
- bump_pattern_use   : 复用计数（随本轮决策事务提交）

全部非阻塞：失败仅日志，不破坏主决策链路。
"""

import logging
from datetime import datetime

from sqlalchemy import select

from app.models.pm_fix_pattern import PMFixPattern

logger = logging.getLogger(__name__)

MAX_PATTERN_BOOST = 0.10   # 评分提升上限
_BOOST_PER_SUCCESS = 0.03  # 每个成功先例折算的评分提升


async def learn_fix_pattern(db, issue_type: str, pattern_text: str, source_decision_id=None) -> bool:
    """沉淀/强化修复模式。同类型已有成功先例则计数+1；否则新建。"""
    try:
        if not issue_type or not pattern_text:
            return False
        row = (
            await db.execute(
                select(PMFixPattern)
                .where(PMFixPattern.issue_type == issue_type)
                .order_by(PMFixPattern.success_count.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(
                PMFixPattern(
                    issue_type=issue_type,
                    pattern_text=pattern_text[:2000],
                    source_decision_id=source_decision_id,
                    success_count=1,
                )
            )
            logger.info('[PM-FixPattern] 沉淀新模式: %s', issue_type)
        else:
            row.success_count = (row.success_count or 0) + 1
            logger.debug('[PM-FixPattern] 强化模式: %s success_count=%s', issue_type, row.success_count)
        await db.commit()
        return True
    except Exception as e:  # noqa: BLE001
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning('[PM-FixPattern] 沉淀失败（非阻塞）: %s', e)
        return False


async def find_best_pattern(db, issue_type: str):
    """查同类型最成功的先例。"""
    try:
        return (
            await db.execute(
                select(PMFixPattern)
                .where(PMFixPattern.issue_type == issue_type)
                .order_by(PMFixPattern.success_count.desc(), PMFixPattern.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    except Exception as e:  # noqa: BLE001
        logger.debug('[PM-FixPattern] 查询失败（非阻塞）: %s', e)
        return None


def pattern_boost(pattern) -> float:
    """把成功先例折算为决策评分提升（封顶 0.10）。"""
    if pattern is None:
        return 0.0
    return min(MAX_PATTERN_BOOST, (pattern.success_count or 0) * _BOOST_PER_SUCCESS)


async def bump_pattern_use(db, pattern) -> None:
    """复用计数 + 最近使用时间（随本轮决策事务提交）。"""
    try:
        pattern.use_count = (pattern.use_count or 0) + 1
        pattern.last_used_at = datetime.now()
        db.add(pattern)
    except Exception as e:  # noqa: BLE001
        logger.debug('[PM-FixPattern] 复用计数失败（非阻塞）: %s', e)
