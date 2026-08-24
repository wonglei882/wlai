"""PM 预防性上下文注入 — 在章节生成前将已知 PM 问题注入 prompt。

核心思路：从 PMDecisionLog / Foreshadow / PMConsistencyState 中提取未解决问题，
作为"创作约束"注入章节生成 prompt，让 AI 在源头避免重复犯错。
"""

from __future__ import annotations

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.pm_decision_log import PMDecisionLog
from app.models.foreshadow import Foreshadow
from app.models.pm_consistency_state import PMConsistencyState

logger = get_logger(__name__)

# P2 信息增益排序参数
_MAX_WARNINGS = 5
_MAX_OVERDUE_FORESHADOWS = 3
_MAX_TOKEN_BUDGET = 800  # 总 token 预算（约 1.5 字/token）


def _rank_by_information_gain(items: list[str], token_budget: int = _MAX_TOKEN_BUDGET) -> list[str]:
    """P2 信息增益排序：贪心选高信息密度的条目，直到 token 预算耗尽。

    信息密度 = len(set(item)) / len(item)（唯一字数占比，去重信息量）
    """
    if not items:
        return []

    # 计算每条的信息密度
    scored = []
    for item in items:
        chars = set(item)
        density = len(chars) / max(len(item), 1)
        scored.append((density, item))

    # 按密度降序
    scored.sort(key=lambda x: x[0], reverse=True)

    # 贪心填充直到 token 预算
    selected = []
    total_tokens = 0
    for _density, item in scored:
        item_tokens = len(item) // 2  # 粗略估算（中文约 1.5 字/token）
        if total_tokens + item_tokens <= token_budget:
            selected.append(item)
            total_tokens += item_tokens
        if total_tokens >= token_budget:
            break

    return selected


async def get_pm_preventive_context(
    db: AsyncSession,
    project_id: str,
    current_chapter: int,
) -> str:
    """获取 PM 预防性上下文（未解决问题 + 逾期伏笔 + 角色一致性约束）。

    在章节生成前调用，将返回值拼入 prompt 的 quality_adjust_prompt 或单独段落。

    Returns:
        结构化的 PM 约束文本（可直接拼入 prompt），无问题时返回空字符串。
    """
    parts: list[str] = []

    # 1. 未解决的 PM 决策（最近 10 章）
    try:
        unresolved_r = await db.execute(
            select(PMDecisionLog)
            .where(
                and_(
                    PMDecisionLog.project_id == project_id,
                    PMDecisionLog.verified.is_(False),
                    PMDecisionLog.created_at.desc(),
                )
            )
            .order_by(PMDecisionLog.created_at.desc())
            .limit(_MAX_WARNINGS)
        )
        unresolved = unresolved_r.scalars().all()

        if unresolved:
            warnings = []
            for d in unresolved:
                msg = d.verify_message or d.fix_action or d.diag_type or '未知问题'
                warnings.append(f'- [{d.diag_type}] 第{d.chapter_number or "?"}章: {msg[:80]}')
            # P2 信息增益排序 + token 预算
            warnings = _rank_by_information_gain(warnings)
            if warnings:
                parts.append('【PM 一致性提醒（请在本章避免重复问题）】\n' + '\n'.join(warnings))
    except Exception as e:
        logger.debug(f'[PM-Prevent] 未解决问题查询失败: {e}')

    # 2. 逾期伏笔（需要回收提醒）
    try:
        overdue_r = await db.execute(
            select(Foreshadow)
            .where(
                and_(
                    Foreshadow.project_id == project_id,
                    Foreshadow.status.in_(['planted', 'stale']),
                    Foreshadow.urgency >= 1,
                )
            )
            .order_by(Foreshadow.urgency.desc())
            .limit(_MAX_OVERDUE_FORESHADOWS)
        )
        overdue = overdue_r.scalars().all()

        if overdue:
            reminders = []
            for fs in overdue:
                urgency_tag = '急需回收' if fs.urgency >= 2 else '建议回收'
                reminders.append(f'- [{urgency_tag}] {fs.title}: {(fs.content or "")[:60]}')
            parts.append('【伏笔回收提醒（请考虑在本章回收）】\n' + '\n'.join(reminders))
    except Exception as e:
        logger.debug(f'[PM-Prevent] 伏笔提醒查询失败: {e}')

    # 3. 最近角色一致性约束（最新状态作为参考）
    try:
        latest_state_r = await db.execute(
            select(PMConsistencyState).where(PMConsistencyState.project_id == project_id).order_by(PMConsistencyState.updated_at.desc()).limit(1)
        )
        latest_state = latest_state_r.scalar_one_or_none()

        if latest_state and latest_state.character_states:
            import json as _json

            states = latest_state.character_states
            if isinstance(states, str):
                states = _json.loads(states)

            if isinstance(states, dict) and states:
                char_lines = []
                for char_name, char_state in list(states.items())[:5]:
                    if isinstance(char_state, dict):
                        location = char_state.get('location', '未知')
                        emotion = char_state.get('emotion', char_state.get('state_after', '未知'))
                        char_lines.append(f'- {char_name}: 位置={location}, 状态={emotion}')
                    elif isinstance(char_state, str):
                        char_lines.append(f'- {char_name}: {char_state[:50]}')

                if char_lines:
                    parts.append('【角色最新状态（请保持一致性）】\n' + '\n'.join(char_lines))
    except Exception as e:
        logger.debug(f'[PM-Prevent] 角色状态查询失败: {e}')

    if not parts:
        return ''

    return '\n\n'.join(parts)
