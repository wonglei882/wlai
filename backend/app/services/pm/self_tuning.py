"""行为自我调参 — 根据工具成功率动态调整 PM 自身行为。

核心机制：
1. 连续 3 次失败 → 自动升级风险等级（存入 pm_session_state.extra_data）
2. 每 5 次执行 → 评估成功率 → 加/松约束
3. 高频错误模式识别（MistakeLog → FailurePattern）
"""

import logging
import math
from contextlib import suppress
from datetime import datetime, timedelta
from sqlalchemy import select, desc, func
from app.models.mistake_log import MistakeLog
from app.models.pm_decision_log import PMDecisionLog
from app.models.pm_v2 import FailurePattern

logger = logging.getLogger(__name__)

# 阈值常量
FAILURES_IN_ROW_THRESHOLD = 3
EVALUATION_INTERVAL = 5
SUCCESS_RATE_LOW = 0.4
SUCCESS_RATE_HIGH = 0.85
RECENT_WINDOW = 20
ROLLBACK_WINDOW = 5  # 参数变更后追踪 N 轮再回检
ROLLBACK_SAMPLE_MIN = 5  # 样本量不足时不回检
PARAM_CONFIDENCE_INC = 0.1  # 变更确认后置信度增量
PARAM_CONFIDENCE_DEC = 0.2  # 变更回滚后置信度减量（惩罚 > 奖励）


# =============================================================================
# P0: 贝叶斯成功率模型（替代纯计数判断）
# Beta(alpha, beta) 建模工具成功率后验分布
# 每次成功 alpha+=1；每次失败 beta+=1
# =============================================================================


class BetaSuccessRate:
    """用 Beta 分布建模成功率后验概率。"""

    def __init__(self, alpha: float = 1.0, beta: float = 1.0):
        self.alpha = alpha
        self.beta = beta

    def update(self, success: bool) -> None:
        if success:
            self.alpha += 1
        else:
            self.beta += 1

    def prob_below(self, threshold: float = 0.5) -> float:
        """P(真实成功率 < threshold) — 贝叶斯后验概率。

        注: a=alpha(成功数+1), b=beta(失败数+1). 新 _beta_cdf 梯形实现
        已通过 6 个解析样例验证，语义与标准 Beta(alpha,beta) 一致。
        """
        try:
            return _beta_cdf(threshold, self.alpha, self.beta)
        except Exception:
            return 0.5

    def expected_rate(self) -> float:
        """后验期望成功率。"""
        return self.alpha / (self.alpha + self.beta) if (self.alpha + self.beta) > 0 else 0.5

    def std_dev(self) -> float:
        """后验标准差 — 衡量不确定性。样本越多 std 越小。"""
        a, b = self.alpha, self.beta
        n = a + b
        if n <= 2:
            return 0.2887  # Beta(1,1) 的 std ≈ 0.2887（最大不确定性）
        variance = (a * b) / (n * n * (n + 1))
        return math.sqrt(variance)

    def uncertainty_penalty(self, k: float = 1.0) -> float:
        """不确定性惩罚值 = k * std_dev，用于决策评分中降低置信度。"""
        return k * self.std_dev()

    def effective_rate(self, k: float = 1.0) -> float:
        """惩罚后有效率 = mean - k * std（Thompson Sampling 思路）。"""
        return max(0.0, self.expected_rate() - k * self.std_dev())

    def total_samples(self) -> int:
        return int(self.alpha + self.beta - 2)  # -2 因为先验 Beta(1,1)

    def should_intervene(self, risk_threshold: float = 0.8) -> tuple[bool, str]:
        """
        当 P(成功率<50%) > risk_threshold 时返回 (True, reason)。
        比"连续3次失败"更稳健：样本少时不激进，样本多时有统计显著性。
        """
        prob = self.prob_below(0.5)
        n = self.total_samples()
        if n < 3:
            return False, '样本不足，暂不干预'
        if prob > risk_threshold:
            return True, f'P(成功率<50%)=[{prob:.0%}]>阈值，统计显著'
        return False, f'P(成功率<50%)=[{prob:.0%}]<=阈值'


def _beta_cdf(x: float, a: float, b: float) -> float:
    """Beta 分布累积分布函数 P(X <= x; a, b)。

    使用复合梯形数值积分。对于 PM 典型场景 (a,b <= 30, 对应样本 < ~60)，
    2000 步误差 < 1e-5，完全满足贝叶斯干预判断精度需求。

    数学验证样例 (已通过对照 scipy/解析解):
        Beta(1,1) CDF(0.5) = 0.5000
        Beta(1,2) CDF(0.5) = 0.7500
        Beta(2,1) CDF(0.5) = 0.2500
        Beta(3,2) CDF(0.5) = 0.3125
        Beta(1,11) CDF(0.5) = 0.9995
        Beta(11,1) CDF(0.5) = 0.0005
    """
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if a <= 0 or b <= 0:
        return 0.5
    try:
        return _beta_cdf_trap(x, a, b)
    except Exception:
        return 0.5


def _beta_cdf_trap(x: float, a: float, b: float, steps: int = 2000) -> float:
    """复合梯形法积分 Beta PDF: ∫_0^x t^(a-1) (1-t)^(b-1) / B(a,b) dt。"""
    logB = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    dx = x / steps
    # PDF 在端点可能发散（a<1 或 b<1），跳过边界采样
    # 首末中点采样（中点法更稳定 + O(h^2)）
    s = 0.0
    for i in range(steps):
        t = (i + 0.5) * dx
        if t <= 0 or t >= 1:
            continue
        log_pdf = (a - 1) * math.log(t) + (b - 1) * math.log(1 - t) - logB
        s += math.exp(log_pdf)
    return max(0.0, min(1.0, s * dx))


async def _get_latest_session_state(db, project_id: str, user_id: str):
    """Q3: 返回 (project_id,user_id) 最近 PMSessionState；无则 None。
    原 7 处重复 select+order_by+limit(1) 提取至此单一函数。"""
    from app.models.pm_session_state import PMSessionState

    r = await db.execute(
        select(PMSessionState)
        .where(PMSessionState.project_id == project_id, PMSessionState.user_id == user_id)
        .order_by(desc(PMSessionState.created_at))
        .limit(1)
    )
    return r.scalar_one_or_none()


# ============================================================================
# 记录
# ============================================================================


async def record_failure(db, tool_name: str, error_type: str, error_message: str, project_id: str, user_id: str, params: dict = None) -> None:
    """记录工具失败到 MistakeLog + 失败计数统计。"""
    try:
        log = MistakeLog(
            project_id=project_id,
            user_id=user_id,
            command_name=tool_name,
            error_type=error_type or 'unknown',
            error_message=str(error_message)[:1000],
            params=params or {},
        )
        db.add(log)

        # 更新高频模式
        await _update_failure_pattern(db, project_id, user_id, tool_name, error_type)

        # 递增连续失败计数（若session_state不存在则静默跳过）
        consecutive = await _increment_consecutive_failures(
            db,
            project_id,
            user_id,
            increment_exec_count=True,
        )

        # 连续失败达阈值 → 升级风险等级
        if consecutive >= FAILURES_IN_ROW_THRESHOLD:
            await _upgrade_risk_level(db, tool_name, project_id, user_id, consecutive)

        # L4 方向1：追踪本轮执行结果到 pending 参数变更
        await _track_param_change_result(db, project_id, user_id, success=False)

        logger.info(f'[self_tuning] recorded failure: {tool_name} ({error_type}) cf={consecutive}')
    except Exception as e:
        logger.exception(f'[self_tuning] record_failure failed: {e}')


async def record_success(db, tool_name: str, project_id: str, user_id: str) -> None:
    """记录工具成功（仅更新计数，不写 MistakeLog）。"""
    try:
        # 每执行 EVALUATION_INTERVAL 次触发评估
        state = await _get_latest_session_state(db, project_id, user_id)
        if state:
            ed = state.extra_data or {}
            st = ed.get('self_tuning', {})
            st['tool_success_count'] = st.get('tool_success_count', 0) + 1
            st['total_exec_count'] = st.get('total_exec_count', 0) + 1
            st.setdefault('fail_count', 0)  # Q4：fail_count 与 total 同源
            st['consecutive_failures'] = 0  # 成功则重置连续失败

            total = st['total_exec_count']
            if total % EVALUATION_INTERVAL == 0:
                # 定期评估
                await _evaluate_and_adjust(db, project_id, user_id)
                # L4 方向1：回检 pending 参数变更（闭环验证）
                await _check_and_rollback(db, project_id, user_id)

            # L4 方向1：追踪本轮执行结果到 pending 参数变更
            await _track_param_change_result(db, project_id, user_id, success=True)

            ed['self_tuning'] = st
            state.extra_data = ed
            await db.commit()
    except Exception as e:
        logger.exception(f'[self_tuning] record_success failed: {e}')


# ============================================================================
# 内部统计
# ============================================================================


async def _increment_consecutive_failures(
    db,
    project_id: str,
    user_id: str,
    increment_exec_count: bool = False,
) -> int:
    """原子递增 consecutive_failures，返回递增后的值。若无 session_state 返回 0。"""
    try:
        state = await _get_latest_session_state(db, project_id, user_id)
        if not state:
            return 0
        ed = state.extra_data or {}
        st = ed.get('self_tuning', {})
        st['consecutive_failures'] = st.get('consecutive_failures', 0) + 1
        st['fail_count'] = st.get('fail_count', 0) + 1  # Q4：与 total 同源
        if increment_exec_count:
            st['total_exec_count'] = st.get('total_exec_count', 0) + 1
        ed['self_tuning'] = st
        state.extra_data = ed
        await db.commit()
        return st['consecutive_failures']
    except Exception:
        return 0


async def _get_consecutive_failures(db, tool_name: str, project_id: str, user_id: str) -> int:
    """查询 tool 的连续失败次数。"""
    try:
        state = await _get_latest_session_state(db, project_id, user_id)
        if state:
            st = (state.extra_data or {}).get('self_tuning', {})
            cf = st.get('consecutive_failures', 0)
            if cf is None:
                cf = 0
            # 从 session_state 读取，不在线查询 MistakeLog（性能优化）
            return cf
        return 0
    except Exception:
        return 0


async def _calculate_success_rate(db, tool_name: str, project_id: str, user_id: str, window: int = RECENT_WINDOW) -> float:
    """计算最近 N 条执行记录的成功率。

    Q4 口径修复：total 和 total_fails 均从 session_state.self_tuning **同源** 取，
    之前 total=session 计数器 / total_fails=MistakeLog 历史全量，口径不一导致
    负值率被 max(0,...) 截为 0（看似"绝对失败"）。"""
    try:
        state = await _get_latest_session_state(db, project_id, user_id)
        if not state:
            return 1.0
        st = (state.extra_data or {}).get('self_tuning', {})
        total = st.get('total_exec_count', 0) or 0
        total_fails = st.get('fail_count', 0) or 0
        if total == 0:
            return 1.0
        return max(0.0, (total - total_fails) / total)
    except Exception:
        return 1.0


async def _update_failure_pattern(db, project_id: str, user_id: str, tool_name: str, error_type: str) -> None:
    """更新高频失败模式。"""
    if not project_id:
        # project_id 为空时无法写入 pm_failure_patterns（NOT NULL），跳过避免事务中断连锁失败
        return
    try:
        # QS1：加命名空间前缀 tune_，避免与 memory.register_failure 的 pattern_type 撞 key
        key = f'tune_{tool_name}:{error_type}'
        r = await db.execute(select(FailurePattern).where(FailurePattern.pattern_type == key).limit(1))
        pattern = r.scalar_one_or_none()
        if pattern:
            pattern.occurrence_count = (pattern.occurrence_count or 0) + 1
            pattern.last_occurred_at = datetime.now()
        else:
            pattern = FailurePattern(
                project_id=project_id,
                pattern_type=key,
                error_description=f'工具 {tool_name} 频繁失败，类型 {error_type}',
                root_cause='',
                recovery_suggestion='',
                occurrence_count=1,
            )
            db.add(pattern)
        await db.commit()
    except Exception as e:
        logger.exception(f'[self_tuning] _update_failure_pattern failed: {e}')
        with suppress(Exception):
            await db.rollback()


# =============================================================================
# P0: 贝叶斯成功率模型 — 核心工具函数
# =============================================================================


async def _build_beta_from_history(
    db,
    project_id: str,
    diag_type: str,
    window_hours: int = 72,
) -> BetaSuccessRate:
    """
    从 PMDecisionLog 历史构建 BetaSuccessRate 实例（用于贝叶斯干预判断）。

    Args:
        db: AsyncSession
        project_id: 项目 ID
        diag_type: 诊断类型
        window_hours: 历史窗口，默认 72h（3 天）

    Returns:
        BetaSuccessRate 实例（alpha/beta 来自历史数据）
    """
    beta = BetaSuccessRate(alpha=1.0, beta=1.0)
    try:
        cutoff = datetime.now() - timedelta(hours=window_hours)
        rows = await db.execute(
            select(
                func.count(PMDecisionLog.id),
                func.sum(1 if PMDecisionLog.fix_result == 'success' else 0),
            )
            .select_from(PMDecisionLog)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type == diag_type,
                PMDecisionLog.created_at >= cutoff,
                PMDecisionLog.fix_attempted == True,  # noqa: E712
            )
        )
        row = rows.one_or_none()
        if row:
            total = row[0] or 0
            successes = row[1] or 0
            failures = total - successes
            beta.alpha += successes
            beta.beta += failures
        return beta
    except Exception as e:
        logger.debug(f'[self_tuning] _build_beta_from_history failed: {e}')
        return beta


async def _get_beta_intervention(
    db,
    project_id: str,
    diag_type: str,
    user_id: str,
) -> tuple[bool, str]:
    """
    查询贝叶斯成功率并返回是否需要干预。

    P0 升级：第 1/2 信号改用 Beta 分布：
    - P(成功率<50%) > 0.8 → skip_round
    - P(成功率<50%) > 0.5 + 已有 1 次失败 → lower_risk
    - n < 3 → 样本不足，暂不干预（向后兼容现有样本少的新项目）

    Returns:
        (should_intervene: bool, reason: str)
    """
    beta = await _build_beta_from_history(db, project_id, diag_type)
    n = beta.total_samples()
    if n < 3:
        return False, f'样本不足(n={n})，暂不干预'
    prob = beta.prob_below(0.5)
    if prob > 0.8:
        return True, f'贝叶斯P(成功率<50%)=[{prob:.0%}]>80%，跳过本轮'
    if prob > 0.5:
        consecutive = await _get_consecutive_failures(db, diag_type, project_id, user_id)
        if consecutive >= 1:
            return True, f'贝叶斯P(成功率<50%)=[{prob:.0%}]>50%且已有失败，降级建议模式'
    return False, f'贝叶斯P(成功率<50%)=[{prob:.0%}]<=50%'


# =============================================================================
# P2-2: 反馈回路增强 — 用 Beta 分布驱动修复策略选择（VQE 式闭环）
# =============================================================================

# 策略阈值
STRATEGY_AGGRESSIVE_THRESHOLD = 0.85  # 成功率 > 0.85 → 激进修复
STRATEGY_CONSERVATIVE_THRESHOLD = 0.4  # 成功率 0.4~0.85 → 保守修复
# 成功率 < 0.4 → 跳过修复，转人工


async def choose_fix_strategy(
    db,
    project_id: str,
    diag_type: str,
) -> tuple[str, float, str]:
    """根据 Beta 分布后验成功率选择修复策略。

    策略分级:
        'aggressive' — 激进修复（直接改正文/状态）
        'conservative' — 保守修复（建伏笔+建议，不直接改正文）
        'skip' — 跳过修复，转人工

    Returns:
        (strategy, expected_rate, reason)
    """
    beta = await _build_beta_from_history(db, project_id, diag_type)
    expected = beta.expected_rate()
    n = beta.total_samples()

    # 样本不足时默认保守（不激进也不跳过）
    if n < 3:
        return 'conservative', expected, f'样本不足(n={n})，默认保守策略'

    if expected >= STRATEGY_AGGRESSIVE_THRESHOLD:
        return 'aggressive', expected, f'成功率[{expected:.0%}]≥85%，激进修复'
    if expected >= STRATEGY_CONSERVATIVE_THRESHOLD:
        return 'conservative', expected, f'成功率[{expected:.0%}]∈[40%,85%)，保守修复'
    return 'skip', expected, f'成功率[{expected:.0%}]<40%，转人工'


# ============================================================================
# 调参逻辑
# ============================================================================


async def _upgrade_risk_level(db, tool_name: str, project_id: str, user_id: str, consecutive: int) -> None:
    """连续失败达阈值 → 动态升级该工具的风险等级。"""
    state = await _get_latest_session_state(db, project_id, user_id)
    if not state:
        return

    ed = state.extra_data or {}
    st = ed.get('self_tuning', {})
    overrides = st.get('risk_overrides', {})

    # 读取当前 risk_level，逐级升级
    current_level = overrides.get(tool_name, 'MEDIUM')
    levels = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
    if current_level in levels:
        idx = min(levels.index(current_level) + 1, len(levels) - 1)
        new_level = levels[idx]
    else:
        new_level = 'HIGH'

    overrides[tool_name] = new_level
    st['risk_overrides'] = overrides
    st['consecutive_failures'] = consecutive
    ed['self_tuning'] = st
    state.extra_data = ed
    await db.commit()

    # L4 方向1：记录参数变更日志（用于后续回检）
    await _log_param_change(
        db,
        project_id,
        user_id,
        param=f'risk_override:{tool_name}',
        old_value=current_level,
        new_value=new_level,
        reason=f'连续失败 {consecutive} 次升级风险等级',
    )

    logger.info(f'[self_tuning] ⬆️ {tool_name} risk_level: {current_level}→{new_level} (consecutive={consecutive})')


async def _evaluate_and_adjust(db, project_id: str, user_id: str) -> None:
    """定期评估：检查成功率 → 自适应加/松约束。"""
    state = await _get_latest_session_state(db, project_id, user_id)
    if not state:
        return

    ed = state.extra_data or {}
    st = ed.get('self_tuning', {})

    # 全局成功率（Q4：session_state 同源口径，与 _calculate_success_rate 一致）
    total = st.get('total_exec_count', 0) or 0
    total_fails = st.get('fail_count', 0) or 0
    rate = max(0.0, (total - total_fails) / total) if total > 0 else 1.0

    # 动态约束（注入 system_prompt 用）
    constraints = st.get('dynamic_constraints', [])

    if rate < SUCCESS_RATE_LOW:
        # 成功率过低 → 加约束
        new_constraint = f'【自调参】近期工具成功率偏低({rate:.0%})，请在执行前确认参数完整性，简化操作步骤'
        if new_constraint not in constraints:
            constraints.append(new_constraint)
            # L4 方向1：记录约束新增变更（用于后续回检）
            await _log_param_change(
                db,
                project_id,
                user_id,
                param='dynamic_constraint_added',
                old_value=None,
                new_value=new_constraint,
                reason=f'成功率 {rate:.0%} < {SUCCESS_RATE_LOW}，加约束',
            )
        logger.info(f'[self_tuning] 📉 rate={rate:.0%}: added constraint')
    elif rate > SUCCESS_RATE_HIGH and len(constraints) > 0:
        # 成功率恢复 → 松约束（删最旧的）
        removed = constraints.pop(0)
        # L4 方向1：记录约束删除变更（用于后续回检）
        await _log_param_change(
            db,
            project_id,
            user_id,
            param='dynamic_constraint_removed',
            old_value=removed,
            new_value=None,
            reason=f'成功率 {rate:.0%} > {SUCCESS_RATE_HIGH}，松约束',
        )
        logger.info(f'[self_tuning] 📈 rate={rate:.0%}: removed constraint: {removed[:50]}')
    else:
        logger.debug(f'[self_tuning] rate={rate:.0%}: no change (constraints={len(constraints)})')

    st['dynamic_constraints'] = constraints
    st['last_eval_rate'] = rate
    st['last_eval_at'] = str(datetime.now())
    ed['self_tuning'] = st
    state.extra_data = ed
    await db.commit()


# ============================================================================
# System prompt 注入
# ============================================================================


async def get_adaptive_prompt(db, project_id: str, user_id: str) -> str:
    """生成自调参结果文本，注入 system_prompt。"""
    state = await _get_latest_session_state(db, project_id, user_id)
    if not state:
        return ''

    ed = state.extra_data or {}
    st = ed.get('self_tuning', {})
    if not isinstance(st, dict):  # 防御：数据库中可能存了 RiskLevel 等非 dict 值
        st = {}

    parts = []
    overrides = st.get('risk_overrides', {})
    constraints = st.get('dynamic_constraints', [])
    rate = st.get('last_eval_rate')

    if overrides and isinstance(overrides, dict):
        level_parts = ['动态风险等级']
        for tool, lv in overrides.items():
            level_parts.append(f'  {tool}: {lv}')
        parts.append('\n'.join(level_parts))

    if constraints:
        parts.append('\n'.join(f'  {c}' for c in constraints))

    if rate is not None:
        parts.append(f'近期工具成功率: {rate:.0%}')

    return '\n\n'.join(parts) if parts else ''


# ============================================================================
# L4 方向1：参数变更回检（闭环验证）
# 每次参数调整记录 change log，追踪后续 N 轮成功率，
# 无改善则自动回滚并标记该参数方向不可信。
# ============================================================================


async def _log_param_change(
    db,
    project_id: str,
    user_id: str,
    param: str,
    old_value,
    new_value,
    reason: str,
) -> None:
    """记录一条参数变更日志到 session_state.self_tuning.param_change_log。"""
    try:
        state = await _get_latest_session_state(db, project_id, user_id)
        if not state:
            return
        ed = state.extra_data or {}
        st = ed.get('self_tuning', {})
        change_log = st.get('param_change_log', [])

        change_log.append(
            {
                'param': param,
                'old_value': old_value,
                'new_value': new_value,
                'changed_at': str(datetime.now()),
                'reason': reason,
                'post_change_results': [],  # 后续每轮的 (success: bool) 追加至此
                'status': 'pending',  # pending / confirmed / rolled_back
                'confidence': 0.5,  # 变更方向的可信度
            }
        )
        # 限制 change_log 长度，保留最近 50 条
        st['param_change_log'] = change_log[-50:]
        ed['self_tuning'] = st
        state.extra_data = ed
        await db.commit()
        logger.info(f'[self_tuning] 📝 param change logged: {param} {old_value}→{new_value} ({reason})')
    except Exception as e:
        logger.exception(f'[self_tuning] _log_param_change failed: {e}')


async def _track_param_change_result(
    db,
    project_id: str,
    user_id: str,
    success: bool,
) -> None:
    """每次工具执行后，将结果追加到所有 pending 变更的 post_change_results。"""
    try:
        state = await _get_latest_session_state(db, project_id, user_id)
        if not state:
            return
        ed = state.extra_data or {}
        st = ed.get('self_tuning', {})
        change_log = st.get('param_change_log', [])

        modified = False
        for entry in change_log:
            if entry.get('status') == 'pending':
                entry['post_change_results'].append(success)
                modified = True

        if modified:
            st['param_change_log'] = change_log
            ed['self_tuning'] = st
            state.extra_data = ed
            await db.commit()
    except Exception as e:
        logger.debug(f'[self_tuning] _track_param_change_result failed: {e}')


async def _check_and_rollback(db, project_id: str, user_id: str) -> None:
    """
    回检所有 pending 参数变更：
    - post_change_results 达到 ROLLBACK_WINDOW 条且样本 ≥ ROLLBACK_SAMPLE_MIN → 评估
    - 改善（成功率 > 变更前） → confirmed + 提升置信度
    - 未改善或下降 → rolled_back + 回滚参数 + 降低置信度
    """
    try:
        state = await _get_latest_session_state(db, project_id, user_id)
        if not state:
            return
        ed = state.extra_data or {}
        st = ed.get('self_tuning', {})
        change_log = st.get('param_change_log', [])

        modified = False
        for entry in change_log:
            if entry.get('status') != 'pending':
                continue
            results = entry.get('post_change_results', [])
            if len(results) < ROLLBACK_WINDOW:
                continue
            # 样本量不足时不回检（避免噪声抖动）
            if len(results) < ROLLBACK_SAMPLE_MIN:
                continue

            post_rate = sum(results) / len(results) if results else 0
            old_value = entry.get('old_value')
            param = entry.get('param')

            # 判断改善：变更后成功率 > 50% 视为改善
            improved = post_rate > 0.5

            if improved:
                entry['status'] = 'confirmed'
                entry['confidence'] = min(1.0, entry.get('confidence', 0.5) + PARAM_CONFIDENCE_INC)
                logger.info(f'[self_tuning] ✅ param change confirmed: {param} (post_rate={post_rate:.0%})')
            else:
                entry['status'] = 'rolled_back'
                entry['confidence'] = max(0.0, entry.get('confidence', 0.5) - PARAM_CONFIDENCE_DEC)
                # 回滚参数
                _apply_param_rollback(st, param, old_value)
                logger.info(f'[self_tuning] ⏮️ param rolled back: {param} → {old_value} (post_rate={post_rate:.0%})')
            modified = True

        if modified:
            st['param_change_log'] = change_log
            ed['self_tuning'] = st
            state.extra_data = ed
            await db.commit()
    except Exception as e:
        logger.exception(f'[self_tuning] _check_and_rollback failed: {e}')


def _apply_param_rollback(st: dict, param: str, old_value) -> None:
    """将参数回滚到旧值。"""
    if param.startswith('risk_override:'):
        tool_name = param.split(':', 1)[1]
        overrides = st.get('risk_overrides', {})
        if old_value and old_value != 'NONE':
            overrides[tool_name] = old_value
        else:
            overrides.pop(tool_name, None)
        st['risk_overrides'] = overrides
    elif param == 'dynamic_constraint_removed':
        # 回滚"删除约束"→ 把约束加回去
        constraints = st.get('dynamic_constraints', [])
        if old_value and old_value not in constraints:
            constraints.append(old_value)
        st['dynamic_constraints'] = constraints
    elif param == 'dynamic_constraint_added':
        # 回滚"新增约束"→ 删掉它
        constraints = st.get('dynamic_constraints', [])
        if old_value in constraints:
            constraints.remove(old_value)
        st['dynamic_constraints'] = constraints
