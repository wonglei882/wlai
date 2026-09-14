"""PM 自进化引擎 — 三层闭环（信号层 → 阈值进化 → 规则生长）。

架构：
1. 信号层    signal aggregation —— 每轮巡检后按维度聚合 PMDecisionLog
   （命中率/误报率/修复率，72h 窗口），写入 PMEvolutionState。
2. 阈值进化  threshold evolution —— 误报偏高/修复率低时，在配置
   min/max 边界内逐步调整扫描参数（运行时覆盖 get_scanner_params）；
   变更后累计新决策评估，无改善自动回滚并降低置信度。
3. 规则生长  rule growth —— 用户驳回反馈学习排除规则（PMExclusionRule），
   巡检时按角色/伏笔/章节/维度过滤噪声；另含维度级节流（连续干净降频）。

开关：pm_features.yaml -> features.optional.self_evolution.enabled。
关闭时所有进化动作安全降级为 no-op（巡检不受影响）。

运行路径：
- scan_all_projects 启动时  -> preload_runtime_overrides(db)
- _scan_single_project 循环内 -> is_dimension_throttled() / filter_exclusions()
- _scan_single_project 收尾 -> evolve_after_round(db, ...)
- feedback 端点驳回          -> learn_from_rejection(db, log)
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, func, delete, case

from app.models.pm_decision_log import PMDecisionLog
from app.models.pm_evolution import (
    PMEvolutionState,
    PMExclusionRule,
    PMEvolutionEvent,
)
from app.services.pm.feature_config import (
    pm_feature_config,
    set_runtime_overrides,
)

logger = logging.getLogger(__name__)

# =============================================================================
# 配置常量
# =============================================================================

# 信号聚合窗口（小时）：近 3 天决策
WINDOW_HOURS = 72
# 误报率超过此值触发"降敏感"进化
FP_RATE_TRIGGER = 0.5
# 修复成功率低于此值（且样本充足）触发"降敏感"进化
FIX_RATE_TRIGGER = 0.4
# 触发进化所需最小决策样本
MIN_DECISIONS_FOR_EVOLVE = 3
# 每次调整步长 = 参数范围的 10%
STEP_RATIO = 0.1
# 变更确认/回滚的置信度奖惩
CONFIDENCE_INC = 0.1
CONFIDENCE_DEC = 0.2
# 变更后累计多少新决策后评估是否回滚
ROLLBACK_EVAL_SAMPLES = 5
# 连续多少轮无 issue 后进入节流
THROTTLE_AFTER_CLEAN = 6
# 节流持续时长（小时）
THROTTLE_DURATION_HOURS = 24

# 可进化参数表：dimension -> {key, sensitivity}
# sensitivity = +1 表示参数调高会增加 issue 产出；-1 表示调高会减少。
_EVOLVABLE_PARAMS: dict[str, dict[str, Any]] = {
    'character_consistency': {'key': 'z_score_threshold', 'sensitivity': -1},
    'foreshadow_age': {'key': 'low_age_threshold', 'sensitivity': -1},
    'quality_score': {'key': 'score_threshold', 'sensitivity': 1},
    'paragraph_format': {'key': 'max_chars', 'sensitivity': -1},
}

# 运行时覆盖缓存（E2 数据源）：dimension -> {key: value}
_runtime_overrides: dict[str, dict[str, float]] = {}
# 节流缓存：(project_id, dimension) -> throttle_until（None 表示未节流）
_throttle_cache: dict[tuple[str, str], datetime | None] = {}

_ISSUE_TO_DIMENSION_CACHE: dict[str, str] = {}


def is_evolution_enabled() -> bool:
    """自进化功能开关。"""
    return pm_feature_config.is_enabled('optional.self_evolution')


def _get_issue_to_dimension() -> dict[str, str]:
    """diag_type -> dimension 反向映射（延迟构建，避免循环导入）。"""
    if not _ISSUE_TO_DIMENSION_CACHE:
        try:
            from app.services.pm.pm_scanners import SCAN_REGISTRY

            for _dim, _meta in SCAN_REGISTRY.items():
                _ISSUE_TO_DIMENSION_CACHE[_meta['issue_type']] = _dim
        except Exception as e:  # noqa: S110 -- 注册表不可用时退化为空映射
            logger.debug(f'[evolution] SCAN_REGISTRY 读取失败: {e}')
    return _ISSUE_TO_DIMENSION_CACHE


def _issue_type_to_dimension(diag_type: str | None) -> str | None:
    if not diag_type:
        return None
    return _get_issue_to_dimension().get(diag_type)


# =============================================================================
# E2: 运行时覆盖层（配合 feature_config.get_scanner_params）
# =============================================================================


async def preload_runtime_overrides(db) -> int:
    """巡检启动时预载所有进化状态的运行时阈值与节流快照。

    返回载入的覆盖参数个数。关闭时清空缓存并返回 0。
    """
    _runtime_overrides.clear()
    _throttle_cache.clear()
    if not is_evolution_enabled():
        return 0
    try:
        rows = (await db.execute(select(PMEvolutionState))).scalars().all()
        loaded = 0
        for st in rows:
            if st.threshold_value is not None and st.threshold_key and st.status != 'disabled':
                _runtime_overrides.setdefault(st.dimension, {})[st.threshold_key] = st.threshold_value
                loaded += 1
            # 节流快照：过期即视为未节流（evolve_after_round 会刷新）
            if st.status == 'throttled' and st.throttle_until and st.throttle_until > datetime.now():
                _throttle_cache[(st.project_id, st.dimension)] = st.throttle_until
            else:
                _throttle_cache[(st.project_id, st.dimension)] = None
        set_runtime_overrides(_runtime_overrides)
        logger.info(f'[evolution] 运行时覆盖预载完成: {loaded} 个参数, {len(_throttle_cache)} 个维度节流快照')
        return loaded
    except Exception as e:
        logger.warning(f'[evolution] 预载运行时覆盖失败（降级为默认参数）: {e}')
        return 0


def is_dimension_throttled(project_id: str, dimension: str) -> bool:
    """检查维度是否处于节流状态（读缓存，无 DB 访问）。"""
    if not is_evolution_enabled():
        return False
    until = _throttle_cache.get((project_id, dimension))
    return bool(until and until > datetime.now())


# =============================================================================
# 排除规则（规则生长层）
# =============================================================================

_EXTRACTORS: dict[str, tuple[str, re.Pattern]] = {
    'pm_agent_character_jump': ('character', re.compile(r'角色\s*([^，,。\s]+?)\s*位置跳变')),
    'pm_agent_foreshadow_stale': ('foreshadow', re.compile(r'伏笔「(.+?)」')),
}


def _extract_exclusion_key(diag_type: str, message: str, chapter_number: int | None):
    """从决策记录提取排除规则键。

    Returns:
        (rule_type, rule_key) 或 (None, None) 表示无法提取（不学习）。
    """
    if diag_type in _EXTRACTORS:
        rule_type, pattern = _EXTRACTORS[diag_type]
        m = pattern.search(message or '')
        if m and m.group(1):
            return rule_type, m.group(1).strip()
        return None, None
    # 按章节抑制：质量评分/段落格式等章节级问题，驳回即排除该章该维度
    if diag_type in ('pm_agent_quality_score_low', 'pm_agent_paragraph_too_long'):
        if chapter_number:
            return 'chapter', str(chapter_number)
        return None, None
    return None, None


async def learn_from_rejection(db, log) -> PMExclusionRule | None:
    """用户驳回 → 学习排除规则（噪声抑制）。

    从 PMDecisionLog 提取结构化键（角色/伏笔/章节），写入 PMExclusionRule，
    并记录 rule_learned 事件。可提取的键不存在时跳过（如世界观漂移）。
    """
    if not is_evolution_enabled():
        return None
    try:
        dimension = _issue_type_to_dimension(log.diag_type)
        if not dimension:
            return None
        rule_type, rule_key = _extract_exclusion_key(
            log.diag_type, log.original_message or '', log.chapter_number
        )
        if not rule_key:
            return None

        # 去重：同范围同类型同键已存在则复用（更新理由）
        existing = (
            await db.execute(
                select(PMExclusionRule).where(
                    PMExclusionRule.project_id == log.project_id,
                    PMExclusionRule.dimension == dimension,
                    PMExclusionRule.rule_type == rule_type,
                    PMExclusionRule.rule_key == rule_key,
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.reason = (log.feedback_note or '')[:500] or existing.reason
            rule = existing
        else:
            rule = PMExclusionRule(
                project_id=log.project_id,
                dimension=dimension,
                rule_type=rule_type,
                rule_key=rule_key,
                reason=(log.feedback_note or f'用户驳回了 {log.diag_type} 决策')[:500],
                source='user_rejection',
                enabled=True,
            )
            db.add(rule)
        _log_event(
            db, log.project_id, dimension, 'rule_learned',
            {'rule_type': rule_type, 'rule_key': rule_key, 'decision_id': str(log.id), 'note': (log.feedback_note or '')[:100]},
        )
        await db.commit()
        logger.info(f'[evolution] 驳回学习排除规则: {dimension}/{rule_type}:{rule_key} (project={log.project_id[:8]})')
        return rule
    except Exception as e:
        logger.warning(f'[evolution] learn_from_rejection 失败: {e}')
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def filter_exclusions(db, project_id: str, dimension: str, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按排除规则过滤 issue，命中规则 +1 计数（随会话提交）。

    Returns:
        过滤后的 issue 列表。
    """
    if not issues or not is_evolution_enabled():
        return issues
    try:
        rules = (
            await db.execute(
                select(PMExclusionRule).where(
                    PMExclusionRule.project_id == project_id,
                    PMExclusionRule.dimension == dimension,
                    PMExclusionRule.enabled.is_(True),
                )
            )
        ).scalars().all()
        if not rules:
            return issues

        kept: list[dict[str, Any]] = []
        excluded = 0
        for issue in issues:
            matched = False
            for rule in rules:
                if _rule_matches(rule, issue):
                    rule.hits = (rule.hits or 0) + 1
                    matched = True
                    break
            if matched:
                excluded += 1
            else:
                kept.append(issue)
        if excluded:
            logger.info(f'[evolution] 排除规则命中 {excluded}/{len(issues)} 个 issue (project={project_id[:8]}, dim={dimension})')
        return kept
    except Exception as e:
        logger.debug(f'[evolution] filter_exclusions 失败（放行全部）: {e}')
        return issues


def _rule_matches(rule: PMExclusionRule, issue: dict[str, Any]) -> bool:
    """判断排除规则是否命中 issue。"""
    key = rule.rule_key
    if rule.rule_type == 'character':
        return issue.get('character') == key
    if rule.rule_type == 'foreshadow':
        return issue.get('title') == key
    if rule.rule_type == 'chapter':
        ch = (
            issue.get('chapter')
            or issue.get('chapter_number')
            or issue.get('planted_chapter')
            or issue.get('from_chapter')
        )
        return ch is not None and str(ch) == key
    if rule.rule_type == 'dimension':
        return key == '*'
    return False


# =============================================================================
# 信号聚合 + 阈值进化 + 节流（每轮巡检后调用）
# =============================================================================


async def _aggregate_signals(db, project_id: str, dimension: str) -> dict[str, float | int]:
    """聚合近 WINDOW_HOURS 小时该维度的决策信号。

    Returns:
        {total, hits, fp, fix_rate, fp_rate}
    """
    issue_types = [
        _type
        for _type, _dim in _get_issue_to_dimension().items()
        if _dim == dimension
    ]
    if not issue_types:
        return {'total': 0, 'hits': 0, 'fp': 0, 'fix_rate': 0.5, 'fp_rate': 0.0}

    cutoff = datetime.now() - timedelta(hours=WINDOW_HOURS)
    rows = (
        await db.execute(
            select(
                func.count(PMDecisionLog.id),
                func.sum(case((PMDecisionLog.fix_result == 'success', 1), else_=0)),
                func.sum(case((PMDecisionLog.verified.is_(True), 1), else_=0)),
                func.sum(case((PMDecisionLog.user_feedback == 'rejected', 1), else_=0)),
                func.sum(case((PMDecisionLog.user_feedback.isnot(None), 1), else_=0)),
            )
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type.in_(issue_types),
                PMDecisionLog.created_at >= cutoff,
            )
        )
    ).one_or_none()
    if not rows or not rows[0]:
        return {'total': 0, 'hits': 0, 'fp': 0, 'fix_rate': 0.5, 'fp_rate': 0.0}

    total = int(rows[0])
    hits = int(rows[1] or 0) + int(rows[2] or 0)
    fp = int(rows[3] or 0)
    feedback_count = int(rows[4] or 0)
    return {
        'total': total,
        'hits': hits,
        'fp': fp,
        'fix_rate': round(hits / total, 3) if total else 0.5,
        'fp_rate': round(fp / feedback_count, 3) if feedback_count else 0.0,
    }


def _param_bounds(dimension: str, key: str) -> tuple[float | None, float | None, float | None]:
    """读取参数 spec 的 default/min/max。"""
    spec = pm_feature_config.get_scanner_param_spec(dimension, key)
    if not spec:
        return None, None, None
    return spec.get('default'), spec.get('min'), spec.get('max')


async def _get_or_create_state(db, project_id: str, dimension: str) -> PMEvolutionState:
    st = (
        await db.execute(
            select(PMEvolutionState).where(
                PMEvolutionState.project_id == project_id,
                PMEvolutionState.dimension == dimension,
            )
        )
    ).scalar_one_or_none()
    if st:
        return st
    st = PMEvolutionState(project_id=project_id, dimension=dimension)
    db.add(st)
    await db.flush()
    return st


def _log_event(db, project_id: str, dimension: str, event_type: str, detail: dict[str, Any]) -> None:
    try:
        db.add(
            PMEvolutionEvent(
                project_id=project_id,
                dimension=dimension,
                event_type=event_type,
                detail=json.dumps(detail, ensure_ascii=False)[:2000],
            )
        )
    except Exception as e:
        logger.debug(f'[evolution] 写事件失败: {e}')


def _evolve_threshold(db, st: PMEvolutionState, signals: dict[str, float | int], default: float, lo: float, hi: float) -> bool:
    """阈值进化决策（单轮）。返回是否发生了阈值变更。"""
    # 回滚评估优先：已有未决变更且累计了新决策
    if st.threshold_value is not None and st.baseline_total_decisions is not None:
        new_decisions = int(signals['total']) - int(st.baseline_total_decisions)
        if new_decisions >= ROLLBACK_EVAL_SAMPLES:
            improved = (
                float(signals['fp_rate']) < float(st.baseline_fp_rate or 0) - 0.05
                or float(signals['fix_rate']) > float(st.baseline_fix_rate or 0.5) + 0.05
            )
            if improved:
                st.confidence = min(1.0, float(st.confidence or 0.5) + CONFIDENCE_INC)
                st.status = 'stable'
                _log_event(
                    db, st.project_id, st.dimension, 'param_change',
                    {'action': 'confirmed', 'param': st.threshold_key, 'value': st.threshold_value,
                     'fp_rate': signals['fp_rate'], 'fix_rate': signals['fix_rate']},
                )
                logger.info(f'[evolution] 阈值变更确认: {st.dimension}.{st.threshold_key}={st.threshold_value} (project={st.project_id[:8]})')
            else:
                old_value = st.threshold_value
                st.threshold_value = st.threshold_original
                st.confidence = max(0.0, float(st.confidence or 0.5) - CONFIDENCE_DEC)
                st.status = 'stable'
                _log_event(
                    db, st.project_id, st.dimension, 'rollback',
                    {'param': st.threshold_key, 'from': old_value, 'to': st.threshold_original,
                     'reason': f'变更后 {new_decisions} 个新决策无改善 (fp_rate={signals["fp_rate"]}, fix_rate={signals["fix_rate"]})'},
                )
                logger.info(f'[evolution] 阈值回滚: {st.dimension}.{st.threshold_key} {old_value}→{st.threshold_original} (project={st.project_id[:8]})')
            st.baseline_total_decisions = None
            st.baseline_fp_rate = None
            st.baseline_fix_rate = None
            return True  # 本轮完成评估，不再叠加变更

    # 变更决策：误报偏高 或 修复率低且样本足 → 降敏感
    total = int(signals['total'])
    fp_rate = float(signals['fp_rate'])
    fix_rate = float(signals['fix_rate'])
    trigger_fp = total >= MIN_DECISIONS_FOR_EVOLVE and fp_rate > FP_RATE_TRIGGER
    trigger_fix = total >= MIN_DECISIONS_FOR_EVOLVE and fix_rate < FIX_RATE_TRIGGER

    if not (trigger_fp or trigger_fix):
        return False

    if st.confidence < 0.2:
        logger.info(f'[evolution] 置信度过低({st.confidence:.2f})，暂停 {st.dimension} 阈值进化 (project={st.project_id[:8]})')
        return False

    meta = _EVOLVABLE_PARAMS.get(st.dimension)
    if not meta:
        return False
    key = meta['key']
    # 降敏感方向：sensitivity=-1 调高，+1 调低
    direction = -1 * int(meta['sensitivity'])
    current = float(st.threshold_value) if st.threshold_value is not None else float(default)
    span = (float(hi) - float(lo)) or 1.0
    step = max(span * STEP_RATIO, 0.01)
    new_value = round(min(float(hi), max(float(lo), current + direction * step)), 4)
    if abs(new_value - current) < 1e-9:
        return False  # 已到边界

    reason = f'误报率{fp_rate:.0%}>{FP_RATE_TRIGGER:.0%}' if trigger_fp else f'修复率{fix_rate:.0%}<{FIX_RATE_TRIGGER:.0%}'
    st.threshold_key = key
    st.threshold_original = st.threshold_original if st.threshold_original is not None else float(default)
    st.threshold_min = float(lo)
    st.threshold_max = float(hi)
    st.threshold_value = new_value
    st.baseline_total_decisions = total
    st.baseline_fp_rate = fp_rate
    st.baseline_fix_rate = fix_rate
    st.status = 'evolving'
    st.last_evolved_at = datetime.now()
    _log_event(
        db, st.project_id, st.dimension, 'param_change',
        {'action': 'set', 'param': key, 'from': current, 'to': new_value, 'reason': reason},
    )
    logger.info(f'[evolution] 阈值进化: {st.dimension}.{key} {current}→{new_value} ({reason}, project={st.project_id[:8]})')
    return True


async def _adjust_throttle(db, st: PMEvolutionState, dimension_issue_count: int) -> None:
    """维度节流：连续干净轮次进入节流，有新 issue 或到期则恢复。"""
    now = datetime.now()
    if st.status == 'throttled' and st.throttle_until and st.throttle_until <= now:
        st.status = 'stable'
        st.consecutive_clean_rounds = 0
        st.throttle_until = None
        _log_event(db, st.project_id, st.dimension, 'throttle_off', {'reason': '节流到期'})
        logger.info(f'[evolution] 维度节流到期恢复: {st.dimension} (project={st.project_id[:8]})')

    if dimension_issue_count > 0:
        st.consecutive_clean_rounds = 0
        if st.status == 'throttled':
            st.status = 'stable'
            st.throttle_until = None
            _log_event(db, st.project_id, st.dimension, 'throttle_off', {'reason': '发现问题，恢复巡检'})
        return

    st.consecutive_clean_rounds = int(st.consecutive_clean_rounds or 0) + 1
    if st.consecutive_clean_rounds >= THROTTLE_AFTER_CLEAN and st.status != 'throttled':
        st.status = 'throttled'
        st.throttle_until = now + timedelta(hours=THROTTLE_DURATION_HOURS)
        _log_event(db, st.project_id, st.dimension, 'throttle_on', {'rounds': st.consecutive_clean_rounds, 'until': str(st.throttle_until)})
        logger.info(f'[evolution] 维度进入节流: {st.dimension} 连续 {st.consecutive_clean_rounds} 轮无 issue (project={st.project_id[:8]})')


async def evolve_after_round(db, project_id: str, issues_by_dimension: dict[str, list], scan_round: str | None = None) -> dict[str, Any]:
    """每轮巡检后执行进化：信号聚合 → 阈值进化 → 节流调整。

    Args:
        db: 巡检会话
        project_id: 项目 ID
        issues_by_dimension: {dimension: [issues]}（过滤后）
        scan_round: 本轮 round id（写入事件日志）

    Returns:
        {dimension: state_dict}，仅包含参与进化的维度。
    """
    if not is_evolution_enabled():
        return {}
    results: dict[str, Any] = {}
    dimensions = set(issues_by_dimension.keys()) | set(_EVOLVABLE_PARAMS.keys())
    try:
        for dimension in dimensions:
            st = await _get_or_create_state(db, project_id, dimension)
            signals = await _aggregate_signals(db, project_id, dimension)
            st.signals_aggregated = int(st.signals_aggregated or 0) + 1
            st.total_decisions = int(signals['total'])
            st.hit_count = int(signals['hits'])
            st.fp_count = int(signals['fp'])
            st.fix_rate = float(signals['fix_rate'])
            st.fp_rate = float(signals['fp_rate'])

            issue_count = len(issues_by_dimension.get(dimension, []))
            await _adjust_throttle(db, st, issue_count)

            if dimension in _EVOLVABLE_PARAMS and signals['total'] > 0:
                meta = _EVOLVABLE_PARAMS[dimension]
                default, lo, hi = _param_bounds(dimension, meta['key'])
                if default is not None and lo is not None and hi is not None:
                    try:
                        _evolve_threshold(db, st, signals, float(default), float(lo), float(hi))
                    except Exception as te:
                        logger.debug(f'[evolution] 阈值进化异常 {dimension}: {te}')

            results[dimension] = st
        # 刷新运行时覆盖缓存
        _refresh_overrides_from_states(results.values())
        await db.commit()
    except Exception as e:
        logger.warning(f'[evolution] evolve_after_round 失败（本轮跳过进化）: {e}')
        try:
            await db.rollback()
        except Exception:
            pass
        return {}
    return {dim: st.to_dict() for dim, st in results.items()}


def _refresh_overrides_from_states(states) -> None:
    """将进化后的状态刷新进运行时覆盖缓存 + feature_config 缓存。"""
    overrides: dict[str, dict[str, float]] = {}
    for st in states:
        if st.threshold_value is not None and st.threshold_key and st.status != 'disabled':
            overrides.setdefault(st.dimension, {})[st.threshold_key] = st.threshold_value
        _throttle_cache[(st.project_id, st.dimension)] = (
            st.throttle_until if st.status == 'throttled' and st.throttle_until and st.throttle_until > datetime.now() else None
        )
    _runtime_overrides.clear()
    _runtime_overrides.update(overrides)
    set_runtime_overrides(overrides)


# =============================================================================
# API 支撑（E5）：总览 / 事件 / 规则 / 重置
# =============================================================================


async def get_evolution_overview(db, project_id: str | None = None) -> dict[str, Any]:
    """进化总览：各维度状态 + 统计。"""
    query = select(PMEvolutionState).order_by(PMEvolutionState.updated_at.desc())
    if project_id:
        query = query.where(PMEvolutionState.project_id == project_id)
    states = (await db.execute(query.limit(200))).scalars().all()
    rule_count = (
        await db.execute(select(func.count()).select_from(PMExclusionRule))
    ).scalar_one() or 0
    event_count = (
        await db.execute(select(func.count()).select_from(PMEvolutionEvent))
    ).scalar_one() or 0
    return {
        'enabled': is_evolution_enabled(),
        'project_id': project_id,
        'states': [s.to_dict() for s in states],
        'rule_count': rule_count,
        'event_count': event_count,
    }


async def list_evolution_events(db, limit: int = 50) -> list[dict]:
    rows = (
        await db.execute(select(PMEvolutionEvent).order_by(PMEvolutionEvent.created_at.desc()).limit(limit))
    ).scalars().all()
    return [r.to_dict() for r in rows]


async def list_exclusion_rules(db, project_id: str | None = None, dimension: str | None = None) -> list[dict]:
    query = select(PMExclusionRule).order_by(PMExclusionRule.created_at.desc())
    if project_id:
        query = query.where(PMExclusionRule.project_id == project_id)
    if dimension:
        query = query.where(PMExclusionRule.dimension == dimension)
    rows = (await db.execute(query.limit(200))).scalars().all()
    return [r.to_dict() for r in rows]


async def reset_project_evolution(db, project_id: str) -> int:
    """重置项目全部进化状态/规则/事件，并清空缓存。返回删除状态行数。"""
    await db.execute(delete(PMEvolutionEvent).where(PMEvolutionEvent.project_id == project_id))
    await db.execute(delete(PMExclusionRule).where(PMExclusionRule.project_id == project_id))
    result = await db.execute(delete(PMEvolutionState).where(PMEvolutionState.project_id == project_id))
    await db.commit()
    _runtime_overrides.clear()
    _throttle_cache.clear()
    set_runtime_overrides({})
    return result.rowcount or 0


async def run_evolution_now(db) -> dict[str, Any]:
    """手动触发一轮进化（对全部有章节的项目），返回进化结果汇总。"""
    from app.database import get_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as _AS

    engine = await get_engine('system')
    AsyncSessionLocal = async_sessionmaker(engine, class_=_AS, expire_on_commit=False)
    result: dict[str, Any] = {}
    async with AsyncSessionLocal() as db2:
        projects = (
            await db2.execute(
                select(PMEvolutionState.project_id).distinct()
            )
        ).scalars().all()
        for pid in projects:
            result[pid] = await evolve_after_round(db2, pid, {})
    return {'projects': len(result), 'summary': 'ok'}
