"""
PM Agent 决策状态层 — 严重性判断与项目历史成功率查询

从 pm_agent_decision.py 拆分而来，用于降低单文件复杂度（控制单文件行数）。

包含：
- _CRITICAL_ISSUE_TYPES / _WARNING_ISSUE_TYPES：严重性分类常量
- classify_severity_by_type()：按 issue_type 判定严重性（共享常量）
- _classify_severity()：兼容 dict 输入的包装
- _get_project_recent_success_rate()：查询项目最近 N 次修复成功率
"""

from typing import Any

from sqlalchemy import select, desc

from app.logger import get_logger
from app.models.pm_decision_log import PMDecisionLog

logger = get_logger(__name__)


# =============================================================================
# 严重性判断
# =============================================================================

_CRITICAL_ISSUE_TYPES = frozenset(
    {
        'character_location_jump',
        'character_consistency_violation',
        'quality_score_low',
        'pm_agent_character_jump',
    }
)

_WARNING_ISSUE_TYPES = frozenset(
    {
        'foreshadow_stale',
        'world_rule_drift',
        'pm_agent_foreshadow_stale',
        'pm_agent_world_drift',
        'outline_drift',
        'pm_agent_outline_drift',
    }
)


def classify_severity_by_type(issue_type: str) -> str:
    """按 issue_type 判定严重性（共享常量，pm_agent 和 pm_agent_decision 均使用）。"""
    if issue_type in _CRITICAL_ISSUE_TYPES:
        return 'critical'
    if issue_type in _WARNING_ISSUE_TYPES:
        return 'warning'
    return 'info'


def _classify_severity(issue: dict[str, Any]) -> str:
    """根据问题字典判断严重性（包装 classify_severity_by_type，兼容 dict 输入）。"""
    return classify_severity_by_type(issue.get('type', ''))


# =============================================================================
# 项目历史成功率查询
# =============================================================================


async def _get_project_recent_success_rate(
    db,
    project_id: str,
    window: int = 10,
) -> float | None:
    """P2: 查询项目最近 N 次修复的成功率（基于 PMDecisionLog.fix_result）。

    Args:
        db: 异步 session
        project_id: 项目 ID
        window: 最近多少次修复（默认 10）

    Returns:
        成功率 [0.0, 1.0]，样本不足（<3 次）返回 None
    """
    try:
        # 取最近 N 条已尝试修复的决策记录（fix_attempted=True）
        rows = await db.execute(
            select(PMDecisionLog.fix_result)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.fix_attempted == True,  # noqa: E712
            )
            .order_by(desc(PMDecisionLog.created_at))
            .limit(window)
        )
        results = [r[0] for r in rows.all() if r[0]]
        if len(results) < 3:
            return None
        success_count = sum(1 for r in results if r == 'success')
        return success_count / len(results)
    except Exception as e:
        logger.debug(f'[PM-Agent P2] 查询项目成功率失败（放行）: {e}')
        return None
