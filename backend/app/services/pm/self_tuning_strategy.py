"""T1.2: Self-Tuning 策略读取层（让数据真正用起来）。

原 self_tuning.py 只写不读 — FailurePattern 表有数据但 diagnose_and_fix 完全不消费。
本模块补上"读"那半：根据项目+维度的连续失败/失败模式，返回恢复策略。

策略枚举：
- 'skip_round'      连续失败次数已达阈值 → 跳过本轮（节省 token）
- 'lower_risk'      失败率高但未到阈值 → 降级为 suggestion 模式（不直接改 chapter）
- ''                (空字符串) 正常处理
"""

from __future__ import annotations

import logging

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pm.self_tuning import (
    FAILURES_IN_ROW_THRESHOLD,
    _get_consecutive_failures,
    _calculate_success_rate,
    _get_beta_intervention,
)

logger = logging.getLogger(__name__)

# 失败计数达到阈值前的"危险区"：连续失败数达到此值后，即使未到阈值也降级为 suggestion
_LOWER_RISK_THRESHOLD = max(1, FAILURES_IN_ROW_THRESHOLD - 1)

# P1: metrics 数据接入阈值
# 内存级成功率极低阈值（与持久化的 SUCCESS_RATE_LOW 解耦：内存指标反映"当下"状态）
_METRICS_SUCCESS_RATE_VERY_LOW = 0.2  # 内存指标成功率 < 20% → 触发 lower_risk
_METRICS_SUCCESS_RATE_SKIP = 0.0  # 内存指标成功率 = 0% 且样本足够 → 触发 skip_round
_METRICS_MIN_SAMPLES = 3  # 内存指标最小样本数


def _compute_recovery_score(
    consecutive: int,
    success_rate: float,
    metrics_rate: float | None,
    beta_prob: float,
    has_skip_hint: bool,
) -> float:
    """多因子加权评分：综合历史/内存/贝叶斯/专家规则，输出 [0,1] 策略分数。

    分数越高 → 系统越"健康" → 可以继续 auto_fix。
    分数越低 → 系统越"疲惫" → 应该 skip_round 或降级。

    权重分配（经验值，可随反馈校准）：
    - cooldown_penalty（40%）：连续失败越多越保守
    - success_rate（30%）：历史成功率，1-success_rate 反映"失败惯性"
    - metrics_rate（15%）：内存级当下状态，无样本时取 0.5（中性）
    - skip_hint（15%）：FailurePattern 专家规则，含 skip 提示时压低分数

    边界处理：
    - metrics_rate=None → 视为 0.5（无数据时不偏倚）
    - beta_prob=0（样本不足时 prob_below 返回 0）→ 不影响

    Returns:
        0.0~1.0：0.6+ 正常，0.3~0.6 降级 lower_risk，<0.3 跳过 skip_round
    """
    # 1) cooldown_penalty：连续失败越多，容忍度越低
    #    3 次连续失败 → penalty=1.0（完全不允许 auto_fix）
    _MAX_CONSECUTIVE = FAILURES_IN_ROW_THRESHOLD  # = 3
    cooldown = min(1.0, consecutive / _MAX_CONSECUTIVE)

    # 2) 历史成功率（1 - success_rate = 失败惯性，值越大系统越"疲惫"）
    history_score = max(0.0, 1.0 - (1.0 - success_rate) * 2)  # 成功率 1.0→1.0，0.4→0.2，0→0
    # 简化：直接用 success_rate，cooldown 负责惩罚
    history_score = max(0.0, success_rate)

    # 3) metrics_rate：无数据取 0.5（不偏倚）
    mem_score = metrics_rate if metrics_rate is not None else 0.5

    # 4) skip_hint：有专家 skip 提示时压低
    hint_score = 0.0 if has_skip_hint else 1.0

    # 加权求和
    score = 0.40 * (1.0 - cooldown) + 0.30 * history_score + 0.15 * mem_score + 0.15 * hint_score

    return max(0.0, min(1.0, score))


async def get_recovery_strategy(
    db: AsyncSession,
    project_id: str,
    user_id: str,
    diag_type: str,
) -> str:
    """根据 self_tuning 数据 + metrics 指标返回该维度的恢复策略。

    P2 升级（原布尔 if 链 → 多因子加权评分）：
    保留硬保底规则（consecutive>=阈值 / beta_prob>0.8 → skip_round），
    其余信号全部量化进 _compute_recovery_score，输出连续分数映射到三档策略：
    - score >= 0.60 → ''（正常 auto_fix）
    - score >= 0.30 → 'lower_risk'（降级 suggestion 模式）
    - score <  0.30 → 'skip_round'（跳过本轮）

    Args:
        db: 异步 session
        project_id: 项目 ID
        user_id: 用户 ID
        diag_type: 诊断类型（foreshadow_stale / world_drift / ...）

    Returns:
        'skip_round' / 'lower_risk' / ''
    """
    try:
        # 0) P1: token 预算超限 → 全局 skip_round（最高优先级，避免继续烧 token）
        if _is_token_budget_exceeded():
            logger.warning('[self_tuning_strategy] skip_round (token_budget_exceeded): 全局 token 预算超限')
            return 'skip_round'

        # 收集各信号
        consecutive = await _get_consecutive_failures(db, diag_type, project_id, user_id)

        # 硬保底：连续失败达到阈值 → 整轮跳过（避免连续烧 token）
        if consecutive >= FAILURES_IN_ROW_THRESHOLD:
            logger.info(
                '[self_tuning_strategy] skip_round: project=%s diag=%s consecutive=%d (>=%d)',
                project_id[:8],
                diag_type,
                consecutive,
                FAILURES_IN_ROW_THRESHOLD,
            )
            return 'skip_round'

        success_rate = await _calculate_success_rate(db, diag_type, project_id, user_id)
        metrics_rate = _get_metrics_success_rate(diag_type)

        # 读 FailurePattern 专家建议
        recovery_hint = await _lookup_failure_pattern(db, project_id, diag_type)
        has_skip_hint = bool(recovery_hint and 'skip' in (recovery_hint or '').lower())

        # 贝叶斯 P(成功率<50%)：样本不足时 prob_below 返回 0（不触发干预）
        beta_prob = 0.0
        try:
            _, beta_reason = await _get_beta_intervention(db, project_id, diag_type, user_id)
            # 从 reason 字符串中提取概率值："P(成功率<50%)=[75%]>80%"
            import re as _re

            m = _re.search(r'P\(成功率<50%\)=\[(\d+)%\]', beta_reason)
            if m:
                beta_prob = int(m.group(1)) / 100.0
        except Exception:  # noqa: S110
            pass

        # 硬保底：贝叶斯 P(成功率<50%) > 80% → 跳过
        if beta_prob > 0.80:
            logger.info(
                '[self_tuning_strategy] skip_round (贝叶斯): project=%s diag=%s beta_prob=%.0f%% (>80%%)',
                project_id[:8],
                diag_type,
                beta_prob * 100,
            )
            return 'skip_round'

        # 多因子评分
        score = _compute_recovery_score(
            consecutive=consecutive,
            success_rate=success_rate,
            metrics_rate=metrics_rate,
            beta_prob=beta_prob,
            has_skip_hint=has_skip_hint,
        )

        # 分数映射到三档策略
        if score >= 0.60:
            return ''  # 正常 auto_fix
        elif score >= 0.30:
            logger.info(
                '[self_tuning_strategy] lower_risk: project=%s diag=%s score=%.2f (0.30~0.60)',
                project_id[:8],
                diag_type,
                score,
            )
            return 'lower_risk'
        else:
            logger.info(
                '[self_tuning_strategy] skip_round: project=%s diag=%s score=%.2f (<0.30)',
                project_id[:8],
                diag_type,
                score,
            )
            return 'skip_round'

    except Exception as e:
        # self_tuning 任何异常都不应阻塞主决策路径
        logger.debug('[self_tuning_strategy] exception (放行): %s', e)
        return ''


def _is_token_budget_exceeded() -> bool:
    """检查全局 token 预算是否超限（包装异常，避免阻塞决策）。"""
    try:
        from app.services.pm.pm_metrics import get_pm_metrics

        return get_pm_metrics().is_token_budget_exceeded()
    except Exception as e:
        logger.debug('[self_tuning_strategy] token budget check exception (放行): %s', e)
        return False


def _get_metrics_success_rate(diag_type: str) -> float | None:
    """从内存级 metrics 获取该 diag_type 的当下成功率。

    返回 None 表示样本不足或 metrics 不可用，调用方应跳过该判断。
    """
    try:
        from app.services.pm.pm_metrics import get_pm_metrics

        return get_pm_metrics().get_type_success_rate(diag_type, min_samples=_METRICS_MIN_SAMPLES)
    except Exception as e:
        logger.debug('[self_tuning_strategy] metrics success_rate exception (放行): %s', e)
        return None


async def _lookup_failure_pattern(db: AsyncSession, project_id: str, diag_type: str) -> str | None:
    """查 FailurePattern 表是否有该维度的失败模式 + 恢复建议。

    FailurePattern.pattern_type 与 PM 的 diag_type 命名不一定一一对应，
    这里做简单前缀映射（foreshadow_stale -> 'foreshadow' 等）。
    """
    try:
        from app.models.pm_v2 import FailurePattern

        # 简单前缀映射，匹配不上就跳过
        pattern_type = _map_diag_type_to_pattern_type(diag_type)
        if not pattern_type:
            return None

        r = await db.execute(
            select(FailurePattern.recovery_suggestion)
            .where(
                FailurePattern.project_id == project_id,
                FailurePattern.pattern_type == pattern_type,
            )
            .order_by(desc(FailurePattern.occurrence_count))
            .limit(1)
        )
        return r.scalar_one_or_none()
    except Exception as e:
        logger.debug('[self_tuning_strategy] _lookup_failure_pattern exception: %s', e)
        return None


# =============================================================================
# ALGORITHM UPGRADE: 硬 if 链 → dict 前缀最长匹配
# 旧代码：顺序 if/elif，无优先级，长关键词被短词截断
# 新代码：按关键词长度降序排列，优先匹配最长关键词
# =============================================================================
_DIAG_TO_PATTERN: tuple[tuple[str, str], ...] = (
    # (关键词, pattern_type)，按长度降序排列，避免 'character' 先匹配 'char' 等短前缀
    ('character_consistency', 'ooc'),
    ('character_jump', 'ooc'),
    ('foreshadow', 'foreshadow'),
    ('world_rule_drift', 'inconsistency'),
    ('worldview', 'inconsistency'),
    ('quality_score', 'quality'),
    ('outline_drift', 'outline'),
    ('paragraph', 'paragraph'),
    ('rhythm', 'pace'),
    ('emotion', 'emotion'),
    ('conflict', 'conflict'),
    ('pace', 'pace'),
    ('hook', 'hook'),
)


def _map_diag_type_to_pattern_type(diag_type: str) -> str:
    """PM diag_type → FailurePattern.pattern_type，最长前缀匹配（避免短关键词截断）。"""
    dt = (diag_type or '').lower()
    best_match = ''
    for keyword, _pattern_type in _DIAG_TO_PATTERN:
        if keyword in dt and len(keyword) > len(best_match):  # noqa: SIM102
            best_match = keyword
    # 用关键词长度查 map，避免重新遍历
    return dict(_DIAG_TO_PATTERN).get(best_match, '')
