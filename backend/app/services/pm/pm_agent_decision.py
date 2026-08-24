"""
PM Agent 决策层 — 从"发现警告"升级到"判断+自动修复+验证"

核心函数：
- diagnose_and_fix(db, issue, project_id, user_id, scan_round)
  对单个问题做决策 → 执行修复 → 重检验证 → 写入 PMDecisionLog

决策策略：
- critical + 有 auto_fix handler → auto_fix + verify
- warning + 有 auto_fix handler → auto_fix + verify（记录 partial/failed）
- warning + 无 handler → alert
- info（旧诊断）→ skip

模块拆分（控制单文件行数）：
- pm_decision_state.py：严重性判断 + 项目历史成功率
  （classify_severity_by_type / _classify_severity / _get_project_recent_success_rate）
- pm_decision_verify.py：修复执行 + 偏离检查 + 验证（_execute_and_verify）
- pm_decision_helpers.py：辅助函数
  （_decompose_repair_priority / _rule_based_sort / _failure_status / _log_decision）
- 本文件：_decide_action（决策阶段）/ _finalize_decision（收尾）/ diagnose_and_fix（入口）
"""

from datetime import datetime, timedelta
from typing import Any
import re
import contextlib

from sqlalchemy import select, func

from app.logger import get_logger
from app.models.pm_decision_log import PMDecisionLog
from app.services.pm.pm_fix_handlers import (
    _has_auto_fix,
    FAILED_COOLDOWN_HOURS,
    ENV_FAILED_COOLDOWN_MINUTES,
    _extract_affected_entities,
    _classify_repair_intent,
    _classify_failure,
)

# handler 注册入口兼容再导出：P2 拆分后定义移至 pm_fix_handlers，
# 但 pm_agent.register_pm_agent() 与单测/e2e 仍从本模块导入这两个名字，
# 缺失会导致容器启动期 PM Agent 注册失败（cannot import name ...）。
from app.services.pm.pm_fix_handlers import _FIX_HANDLERS, register_pm_handlers  # noqa: F401

# 决策链拆分兼容再导出（第二批）：tests/unit 下 8 个测试文件从本模块导入以下私有符号，
# 定义已迁至 pm_fix_handlers（_fix_* 具体实现在 pm_fix_executors），
# 断链会导致 ImportError 且 pytest 收集中断（test_goal_stability.py）。
from app.services.pm.pm_fix_executors import (  # noqa: F401
    _fix_outline_drift,
    _fix_quality_low,
)
from app.services.pm.pm_fix_handlers import (  # noqa: F401
    _check_goal_drift,
    _execute_fix,
    _verify_character_fix,
    _verify_fix,
    _verify_quality_fix,
    _verify_world_fix,
    _verify_world_keywords,
)

logger = get_logger(__name__)

# 止血 #3：跨轮自动修复重试上限——近 7 天内同一项目+同一类型的修复尝试（fix_attempted=True）
# 达到该次数后转人工，防止"每轮巡检都重试同一个修不好的问题"的无限循环。
MAX_AUTO_FIX_ATTEMPTS = 3


# =============================================================================
# 严重性判断 / 项目历史成功率 → 拆分到 pm_decision_state.py
# =============================================================================
from app.services.pm.pm_decision_state import (  # noqa: E402, F401
    classify_severity_by_type,
    _classify_severity,
    _get_project_recent_success_rate,
)

# =============================================================================
# 辅助函数已拆分到 pm_decision_helpers.py（控制文件行数 < 800）
# =============================================================================
from app.services.pm.pm_decision_helpers import (  # noqa: E402, F401
    _decompose_repair_priority,
    _rule_based_sort,
    _failure_status,
    _log_decision,
    _compute_decision_score,
    _get_consecutive_failures,
    _get_recent_attempt_count,
)


# (拆分到 pm_decision_helpers.py 的函数实现已删除)


# =============================================================================
# 修复执行 + 偏离检查 + 验证 → 拆分到 pm_decision_verify.py
# =============================================================================
from app.services.pm.pm_decision_verify import _execute_and_verify  # noqa: E402, F401

# =============================================================================
# 核心决策入口
# =============================================================================


async def _maybe_socratic_redirect(db, issue, project_id, user_id, diag_type, severity):
    """苏格拉底引导拦截（companion 可选功能，默认关闭）。

    命中引导规则时返回 decision='guide' 的结果字典（与 manual/skip 短路同形状），
    交由用户逐步作答；未命中 / 功能关闭 / 异常时返回 None，主链路行为不变。
    """
    try:
        from app.services.companion.socratic import socratic_redirect_if_needed

        return await socratic_redirect_if_needed(db, issue, project_id, user_id, diag_type, severity)
    except Exception as e:
        logger.warning(f'[PM-Agent] 苏格拉底引导拦截失败(跳过): {e}')
        return None


async def _decide_action(
    db,
    issue: dict[str, Any],
    project_id: str,
    user_id: str,
    scan_round: str,
    total_issues_in_scan: int,
    diag_type: str,
    severity: str,
    original_message: str,
) -> tuple[dict | None, str, str, bool]:
    """Q1 重构：diagnose_and_fix 的「决策阶段」。

    返回 (early_result, decision, decision_reason, is_lower_risk)。
    - early_result != None 表示短路（manual/cooldown/skip_approved/skip_self_tuning
      / manual_low_success_rate / skip_no_handler 等短路径直接返回）。
    - 否则进入修复执行阶段。
    """
    has_fix = _has_auto_fix(diag_type)
    # --- 失败冷却/用户驳回/接受检查（状态机） ---
    failure_state = await _failure_status(db, project_id, diag_type)
    if has_fix and failure_state:
        if failure_state == 'manual':
            # 用户驳回过：转人工，1h 去重
            logger.info(f'[PM-Agent 决策] 转人工: type={diag_type} project={project_id[:8]}（用户驳回过，等待人工处理）')
            try:
                dup = await db.execute(
                    select(func.count())
                    .select_from(PMDecisionLog)
                    .where(
                        PMDecisionLog.project_id == project_id,
                        PMDecisionLog.diag_type == diag_type,
                        PMDecisionLog.decision == 'manual',
                        PMDecisionLog.created_at >= datetime.now() - timedelta(hours=1),
                    )
                )
                if (dup.scalar_one() or 0) == 0:
                    await _log_decision(
                        db=db,
                        project_id=project_id,
                        user_id=user_id,
                        issue=issue,
                        severity=severity,
                        decision='manual',
                        decision_reason='用户驳回过同类修复，转人工处理',
                        fix_action='',
                        fix_result='skipped',
                        fix_attempted=False,
                        verified=False,
                        verified_at=None,
                        verify_message='等待人工处理',
                        scan_round=scan_round,
                        original_message=original_message,
                        fix_details=None,
                    )
                    await db.commit()
            except Exception as log_e:
                logger.warning(f'[PM-Agent 决策] 记录 manual 决策失败（非阻塞）: {log_e}')
                await db.rollback()
            result = {
                'type': diag_type,
                'severity': severity,
                'decision': 'manual',
                'fix_action': '',
                'fix_result': 'skipped',
                'fix_attempted': False,
                'verified': False,
                'verify_message': '等待人工处理（用户驳回）',
                'decision_log_id': None,
            }
            return result, 'manual', '用户驳回', False

        if failure_state == 'skip_approved':
            result = {
                'type': diag_type,
                'severity': severity,
                'decision': 'skip',
                'fix_action': '',
                'fix_result': 'skipped_approved',
                'fix_attempted': False,
                'verified': True,
                'verify_message': '用户已接受（7 天内不重复修复）',
                'decision_log_id': None,
            }
            return result, 'skip', '用户已接受跳过', False

        # cooldown：1h 去重写决策日志，避免历史断层
        logger.debug(f'[PM-Agent 决策] 冷却中: type={diag_type} project={project_id[:8]}')
        cooldown_log_id = None
        try:
            dup = await db.execute(
                select(func.count())
                .select_from(PMDecisionLog)
                .where(
                    PMDecisionLog.project_id == project_id,
                    PMDecisionLog.diag_type == diag_type,
                    PMDecisionLog.decision == 'cooldown',
                    PMDecisionLog.created_at >= datetime.now() - timedelta(hours=1),
                )
            )
            if (dup.scalar_one() or 0) == 0:
                cd_log = await _log_decision(
                    db=db,
                    project_id=project_id,
                    user_id=user_id,
                    issue=issue,
                    severity=severity,
                    decision='cooldown',
                    decision_reason='同类修复失败过，冷却期内跳过本轮',
                    fix_action='',
                    fix_result='skipped_cooldown',
                    fix_attempted=False,
                    verified=False,
                    verified_at=None,
                    verify_message=f'冷却中（同类修复失败过，冷却 {FAILED_COOLDOWN_HOURS}h / 环境类 {ENV_FAILED_COOLDOWN_MINUTES}min）',
                    scan_round=scan_round,
                    original_message=original_message,
                    fix_details=None,
                )
                await db.commit()
                cooldown_log_id = cd_log.id if cd_log else None
            else:
                await db.rollback()
        except Exception as log_e:
            logger.warning(f'[PM-Agent 决策] 记录 cooldown 决策失败（非阻塞）: {log_e}')
            await db.rollback()
        result = {
            'type': diag_type,
            'severity': severity,
            'decision': 'cooldown',
            'fix_action': '',
            'fix_result': 'skipped_cooldown',
            'fix_attempted': False,
            'verified': False,
            'verify_message': f'冷却中（同类修复失败过，冷却 {FAILED_COOLDOWN_HOURS}h / 环境类 {ENV_FAILED_COOLDOWN_MINUTES}min）',
            'decision_log_id': cooldown_log_id,
        }
        return result, 'cooldown', '冷却中', False

    # --- 跨轮重试上限（止血 #3）：近 7 天同类修复尝试达上限 → 转人工，防无限重试循环 ---
    if has_fix:
        attempt_count = await _get_recent_attempt_count(db, project_id, diag_type, days=7)
        if attempt_count >= MAX_AUTO_FIX_ATTEMPTS:
            logger.info(
                f'[PM-Agent 决策] 重试上限: type={diag_type} project={project_id[:8]} 近7天已尝试 {attempt_count} 次 ≥ 上限 {MAX_AUTO_FIX_ATTEMPTS}'
            )
            try:
                dup = await db.execute(
                    select(func.count())
                    .select_from(PMDecisionLog)
                    .where(
                        PMDecisionLog.project_id == project_id,
                        PMDecisionLog.diag_type == diag_type,
                        PMDecisionLog.decision == 'manual',
                        PMDecisionLog.created_at >= datetime.now() - timedelta(hours=1),
                    )
                )
                if (dup.scalar_one() or 0) == 0:
                    await _log_decision(
                        db=db,
                        project_id=project_id,
                        user_id=user_id,
                        issue=issue,
                        severity=severity,
                        decision='manual',
                        decision_reason=f'自动修复连续失败达上限（近7天已尝试 {attempt_count}/{MAX_AUTO_FIX_ATTEMPTS} 次），转人工处理',
                        fix_action='',
                        fix_result='skipped',
                        fix_attempted=False,
                        verified=False,
                        verified_at=None,
                        verify_message=f'自动修复连续失败达上限（近7天已尝试 {attempt_count} 次，达上限 {MAX_AUTO_FIX_ATTEMPTS}），等待人工处理',
                        scan_round=scan_round,
                        original_message=original_message,
                        fix_details=None,
                    )
                    await db.commit()
            except Exception as log_e:
                logger.warning(f'[PM-Agent 决策] 记录 manual 决策失败（非阻塞）: {log_e}')
                await db.rollback()
            _cap_verify_msg = f'自动修复连续失败达上限（近7天已尝试 {attempt_count} 次，达上限 {MAX_AUTO_FIX_ATTEMPTS}），等待人工处理'
            result = {
                'type': diag_type,
                'severity': severity,
                'decision': 'manual',
                'fix_action': '',
                'fix_result': 'skipped',
                'fix_attempted': False,
                'verified': False,
                'verify_message': _cap_verify_msg,
                'decision_log_id': None,
            }
            return result, 'manual', f'自动修复连续失败达上限（{attempt_count}/{MAX_AUTO_FIX_ATTEMPTS}）', False

    # --- Self-Tuning 策略闭环 ---
    from app.services.pm.self_tuning_strategy import get_recovery_strategy

    strategy = await get_recovery_strategy(db, project_id, user_id, diag_type) if has_fix else ''
    if strategy == 'skip_round':
        logger.info(f'[PM-Agent 决策] self_tuning 跳过: type={diag_type} project={project_id[:8]}')
        try:
            await _log_decision(
                db=db,
                project_id=project_id,
                user_id=user_id,
                issue=issue,
                severity=severity,
                decision='skip',
                decision_reason='self_tuning 连续失败达阈值，跳过本轮',
                fix_action='',
                fix_result='skipped_self_tuning',
                fix_attempted=False,
                verified=False,
                verified_at=None,
                verify_message='self-tuning 跳过（连续失败达阈值）',
                scan_round=scan_round,
                original_message=original_message,
                fix_details=None,
            )
            await db.commit()
        except Exception:
            await db.rollback()
        result = {
            'type': diag_type,
            'severity': severity,
            'decision': 'skip',
            'fix_action': '',
            'fix_result': 'skipped_self_tuning',
            'fix_attempted': False,
            'verified': False,
            'verify_message': 'self-tuning 跳过（连续失败达阈值，避免无效重试）',
            'decision_log_id': None,
        }
        return result, 'skip', 'self_tuning 跳过', False

    is_lower_risk = strategy == 'lower_risk'
    if is_lower_risk:
        logger.info(f'[PM-Agent 决策] self_tuning 降级: type={diag_type} project={project_id[:8]}（失败率高，降级为 suggestion 模式）')

    # P0: 多因子评分模型（替换项目历史成功率布尔判断）
    # 决策分 = 修复收益 - 修复风险 - 不确定性惩罚
    # ≥ 0.50 → auto_fix  |  0.30~0.49 → auto_fix(suggestion_only)  |  < 0.30 → manual
    # L4 方向2：引入不确定性惩罚（Beta 分布 std），样本少时倾向保守
    project_success_rate = await _get_project_recent_success_rate(db, project_id)
    _consecutive_cooldown = await _get_consecutive_failures(db, project_id, diag_type)
    _severity_val = 1.0 if severity == 'critical' else 0.8
    _confidence_val = 0.9 if diag_type in ('character_location_jump', 'pm_agent_character_jump') else 0.8

    # L4 方向3：数据驱动规则微调评分（轻量油路接入）
    # promoted_rules: [ {doc, confidence, count, score, id} ]
    _promoted_boost_conf = 0.0
    _promoted_extra_cooldown = 0.0
    try:
        from app.services.pm.self_evolve import BehaviorMemory  # noqa: E402

        _prs = BehaviorMemory.get_promoted_rules(project_id=project_id)
        if _prs:
            _issue_text = ' '.join(
                [
                    diag_type or '',
                    str(issue.get('title', '') or ''),
                    str(issue.get('description', '') or ''),
                ]
            ).lower()
            for _r in _prs:
                _doc = (_r.get('doc') or '').lower()
                if not _doc:
                    continue
                # 关键字重叠作为简单匹配（子串即可，避免重依赖 TF-IDF）
                _tokens = [_t for _t in set(re.findall(r'[\w\u4e00-\u9fff]{2,}', _doc)) if _t in _issue_text]
                if len(_tokens) == 0:
                    continue
                _rc = float(_r.get('confidence', 0.5))
                _score = float(_r.get('score', 0.5))
                if _rc >= 0.7 and _score >= 0.6:
                    # 高置信正向规则 → 增强扫描器置信度（相信经验）
                    _promoted_boost_conf = min(0.10, _promoted_boost_conf + 0.05 * _rc)
                elif _rc >= 0.5 and _score < 0.4:
                    # 历史上负面经验型规则 → 额外冷却（更保守）
                    _promoted_extra_cooldown = min(0.20, _promoted_extra_cooldown + 0.05)
    except Exception as _prom_e:
        logger.debug(f'[L4] promoted rules 接入失败 (忽略): {_prom_e}')

    # L4 方向2：构建 BetaSuccessRate 计算不确定性惩罚
    # critical 不做探索（安全第一），只用已知最稳方案
    _uncertainty_penalty = 0.0
    if severity != 'critical':
        from app.services.pm.self_tuning import _build_beta_from_history

        try:
            _beta = await _build_beta_from_history(db, project_id, diag_type)
            _uncertainty_penalty = _beta.uncertainty_penalty(k=1.0)
        except Exception as e:
            logger.debug(f'[L4] Beta 不确定性度量失败, 跳过惩罚: {e}')

    # L4 方向3：promoted rules 叠加微调
    _pr_confidence = min(1.0, _confidence_val + _promoted_boost_conf)
    _pr_cooldown = min(1.0, min(1.0, _consecutive_cooldown / 3.0) + _promoted_extra_cooldown)

    # L5 反思闭环：同类自动修复的历史失败根因 → 惩罚评分 + 注入决策理由。
    # 失败模式由 _execute_and_verify 写入（decision_{diag_type}），此处只读不写。
    _reflection_penalty = 0.0
    _reflection_note = ''
    try:
        from app.services.pm.pm_decision_helpers import _get_recent_decision_failures

        _rf = await _get_recent_decision_failures(db, project_id, diag_type)
        if _rf and _rf.get('count', 0) >= 2:
            # 连续≥2 次同类失败：评分按次数递减惩罚（封顶 0.2），理由携带根因
            _reflection_penalty = min(0.20, 0.05 * _rf['count'])
            _reflection_note = f"；反思：同类修复已失败{_rf['count']}次，上次原因：{_rf.get('last_cause', '')[:80]}"
            logger.info(
                f'[PM-Agent 反思] 同类失败×{_rf["count"]}，评分惩罚 -{_reflection_penalty:.2f}: '
                f'type={diag_type} project={project_id[:8]}'
            )
    except Exception as _ref_e:
        logger.debug(f'[PM-Agent 反思] 读失败模式失败（忽略）: {_ref_e}')

    _score = _compute_decision_score(
        severity_val=_severity_val,
        success_rate=(project_success_rate if project_success_rate is not None else 0.7),
        cooldown_penalty=_pr_cooldown,
        issue_confidence=_pr_confidence,
        drift_risk=0.0,  # drift 由 _execute_and_verify 中用真实 fix_action 评估
        uncertainty_penalty=_uncertainty_penalty,
    ) - _reflection_penalty
    if has_fix and severity in ('critical', 'warning'):
        # 方案一：自主等级阈值统一（PMAutonomyConfig.level 调制阈值；
        # 开关关闭/无配置行/异常 → advisor_plus 阈值 = 历史硬编码行为）
        _level = ''
        try:
            from app.services.pm.pm_decision_policy import classify_by_score, get_effective_level, get_thresholds_for_level

            _level = await get_effective_level(db, project_id)
            decision, decision_reason = classify_by_score(_score, get_thresholds_for_level(_level), severity, level=_level)
        except Exception as e:
            logger.debug(f'[PM-Agent 决策] 自主等级接入异常，回退默认阈值: {e}')
            if _score >= 0.50:
                decision = 'auto_fix'
                decision_reason = f'{severity} 问题，评分={_score:.2f}，执行自动修复{_reflection_note}'
            elif _score >= 0.30:
                decision = 'auto_fix'
                decision_reason = f'{severity} 问题，评分={_score:.2f}，降级为 suggestion 模式{_reflection_note}'
            else:
                decision = 'manual'
                decision_reason = f'{severity} 问题，评分={_score:.2f}，风险过大，转人工处理{_reflection_note}'
    elif has_fix:
        decision = 'auto_fix'
        decision_reason = '有修复 handler，执行自动修复'
    else:
        decision = 'skip'
        decision_reason = '无可用自动修复，跳过'

    return None, decision, decision_reason, is_lower_risk


async def _finalize_decision(
    db,
    issue: dict[str, Any],
    project_id: str,
    user_id: str,
    scan_round: str,
    diag_type: str,
    severity: str,
    original_message: str,
    decision: str,
    decision_reason: str,
    exec_state: dict[str, Any],
    goal_id: str,
    original_goal: dict[str, Any],
) -> dict[str, Any]:
    """Q1 重构：诊断/修复/验证后的「日志 + 目标向量收尾 + commit + metrics」阶段。"""
    fix_action = exec_state.get('fix_action', '')
    fix_result = exec_state.get('fix_result', 'skipped')
    fix_attempted = bool(exec_state.get('fix_attempted', False))
    verified = bool(exec_state.get('verified', False))
    verified_at = exec_state.get('verified_at')
    verify_message = exec_state.get('verify_message', '')
    drift_result = exec_state.get('drift_result') or {}
    fix_start_time = exec_state.get('_fix_start_time')

    # ===== 目标向量收尾：写入 GoalStabilityLog 的 fix_action / drift_score =====
    try:
        from app.models.goal_stability_log import GoalStabilityLog

        await db.execute(
            GoalStabilityLog.__table__.update()
            .where(GoalStabilityLog.goal_id == goal_id)
            .values(
                fix_action={'fix_action': fix_action, 'intent': original_goal['repair_intent']},
                drift_score=drift_result.get('drift_score', 0),
                drift_type=drift_result.get('drift_type'),
                updated_at=datetime.now(),
            )
        )
    except Exception as update_goal_e:
        logger.debug(f'[PM-Agent 目标监控] 更新目标记录失败（非阻塞）: {update_goal_e}')

    # ===== 记录 =====
    log = None
    try:
        import json as _json

        fix_details_dict = {
            'fix_result_detail': fix_action,
            'verify_message': verify_message,
        }
        # 从 fix_action 中提取建议内容（如 outline_drift 的 LLM 建议）
        # fix_action 格式: 描述行+换行+建议内容 -> 提取建议到 suggestion 字段
        if fix_action and '\n' in fix_action:
            _parts = fix_action.split('\n', 1)
            if len(_parts) > 1 and _parts[1].strip():
                fix_details_dict['suggestion'] = _parts[1].strip()[:500]
        if issue.get('llm_reasoning'):
            fix_details_dict['llm_reasoning'] = issue['llm_reasoning']
        if drift_result.get('drift_score', 0) > 0:
            fix_details_dict['goal_drift'] = drift_result
        if fix_result == 'failed':
            # 止血 #1：显式失败分类留痕——优先用执行期按异常类型判定的暂存值
            # （_execute_fix 捕获异常时写入 issue['_failure_kind']），
            # 缺失/非法时回退关键词法（兼容历史路径与验证失败场景）
            failure_kind = issue.get('_failure_kind')
            if failure_kind not in ('env', 'logic'):
                failure_kind = _classify_failure(verify_message or fix_action or '')
            fix_details_dict['failure_kind'] = failure_kind

        fix_details = _json.dumps(fix_details_dict, ensure_ascii=False)

        # 止血 #5：预算降级留痕——LLM reasoning 带 budget_degraded 标记时同步到 decision_reason，
        # 使"预算耗尽导致规则引擎降级"在决策日志中可追溯。
        if 'budget_degraded' in str(issue.get('llm_reasoning') or '') and 'budget_degraded' not in decision_reason:
            decision_reason = f'{decision_reason}; budget_degraded'

        log = await _log_decision(
            db=db,
            project_id=project_id,
            user_id=user_id,
            issue=issue,
            severity=severity,
            decision=decision,
            decision_reason=decision_reason,
            fix_action=fix_action,
            fix_result=fix_result,
            fix_attempted=fix_attempted,
            verified=verified,
            verified_at=verified_at,
            verify_message=verify_message,
            scan_round=scan_round,
            original_message=original_message,
            fix_details=fix_details,
        )
    except Exception as log_e:
        logger.warning(f'[PM-Agent 决策] 记录决策日志失败（非阻塞）: {log_e}')
        log = None

    # ===== 统一事务边界 =====
    try:
        await db.commit()
    except Exception as commit_e:
        logger.warning(f'[PM-Agent 决策] commit 失败，回滚: {commit_e}')
        await db.rollback()

    # ===== 指标采集 =====
    try:
        from app.services.pm.pm_metrics import get_pm_metrics
        import time as _time_metric

        metrics = get_pm_metrics()
        if fix_attempted:
            elapsed = _time_metric.time() - fix_start_time if fix_start_time else 0
            metrics.record_fix(diag_type, fix_result or 'failed', elapsed)
        metrics.record_verify(verified)
    except Exception as e:
        logger.debug(f'[PM] metrics 记录失败 (忽略): {e}')

    return {
        'type': diag_type,
        'severity': severity,
        'decision': decision,
        'fix_action': fix_action,
        'fix_result': fix_result,
        'fix_attempted': fix_attempted,
        'verified': verified,
        'verify_message': verify_message,
        'decision_log_id': log.id if log else None,
    }


async def diagnose_and_fix(
    db,
    issue: dict[str, Any],
    project_id: str,
    user_id: str,
    scan_round: str,
    total_issues_in_scan: int = 0,
) -> dict[str, Any]:
    """对单个问题做决策 → 执行修复 → 重检验证 → 写入 PMDecisionLog。

    Q1 重构：原 ~534 行巨型函数拆为三段子函数调用，编排层 < 60 行：
      1. _decide_action      — 决策分支 / 短路（manual/cooldown/skip_*）
      2. _execute_and_verify  — 修复 + 偏离检查 + 验证
      3. _finalize_decision  — 日志 + commit + metrics

    T0.3 入口防御性 rollback；P2 问题密度与项目成功率差异化策略保持不变。
    """
    # ========== 入口防御：确保 session 干净事务起点 ==========
    with contextlib.suppress(Exception):
        await db.rollback()

    import uuid
    from app.models.goal_stability_log import GoalStabilityLog

    diag_type = issue.get('type', '')
    severity = _classify_severity(issue)
    original_message = issue.get('message', issue.get('chapter_range', ''))

    # ===== 记录原始目标向量 =====
    goal_id = str(uuid.uuid4())
    original_goal = {
        'issue_type': diag_type,
        'affected_entities': _extract_affected_entities(issue),
        'repair_intent': _classify_repair_intent(diag_type),
        'chapter_range': issue.get('chapter_range', ''),
    }
    try:
        db.add(
            GoalStabilityLog(
                goal_id=goal_id,
                project_id=project_id,
                scan_round=scan_round,
                original_goal=original_goal,
            )
        )
        await db.flush()
    except Exception as goal_e:
        logger.debug(f'[PM-Agent 目标监控] 记录目标失败（非阻塞）: {goal_e}')

    logger.info(f'[PM-Agent 决策] 开始处理: type={diag_type} severity={severity}')

    # ===== 阶段 0：苏格拉底引导拦截（companion 可选，默认关闭） =====
    socratic_result = await _maybe_socratic_redirect(db, issue, project_id, user_id, diag_type, severity)
    if socratic_result is not None:
        return socratic_result

    # ===== 阶段 1：决策 =====
    early_result, decision, decision_reason, is_lower_risk = await _decide_action(
        db,
        issue,
        project_id,
        user_id,
        scan_round,
        total_issues_in_scan,
        diag_type,
        severity,
        original_message,
    )
    if early_result is not None:
        return early_result

    # ===== 阶段 2：修复 + 验证 =====
    #   - _execute_and_verify 内部会对 decision != auto_fix 的情况（manual/skip）直接返回 early_result
    early_result, exec_state = await _execute_and_verify(
        db,
        issue,
        project_id,
        user_id,
        decision,
        is_lower_risk,
        original_goal,
        decision_reason,
        diag_type,
        scan_round,
        severity,
        original_message,
    )
    if early_result is not None:
        return early_result

    # ===== 阶段 3：收尾（日志/commit/metrics） =====
    return await _finalize_decision(
        db,
        issue,
        project_id,
        user_id,
        scan_round,
        diag_type,
        severity,
        original_message,
        decision,
        decision_reason,
        exec_state,
        goal_id,
        original_goal,
    )
