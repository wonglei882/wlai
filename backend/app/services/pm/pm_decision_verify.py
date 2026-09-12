"""
PM Agent 决策验证层 — 修复执行 + 偏离检查 + 验证

从 pm_agent_decision.py 拆分而来，用于降低单文件复杂度（控制单文件行数）。

包含：
- _execute_and_verify()：对 auto_fix/manual/skip 决策执行修复、偏离检查与验证
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, func

import logging
from app.models.pm_decision_log import PMDecisionLog
from app.services.pm.pm_decision_helpers import _log_decision
from app.services.pm.pm_fix_handlers import (
    _execute_fix,
    _verify_fix,
    _check_goal_drift,
    _classify_failure,
)

logger = logging.getLogger(__name__)


async def _record_decision_failure(db, project_id: str, diag_type: str, verify_message: str) -> None:
    """L5 反思闭环：决策修复失败/偏离时，将根因摘要 upsert 到 FailurePattern。

    - pattern_type = f'decision_{diag_type}'（与生成侧失败模式命名空间隔离）
    - root_cause 携带验证摘要，供 _decide_action 下轮注入"上次为什么失败"
    - 不主动 commit：随外层 _finalize_decision 的事务一起落库
    失败静默（非阻塞），不影响主决策流程。
    """
    try:
        from app.models.pm_v2 import FailurePattern

        pat_key = f'decision_{diag_type}'
        existing_r = await db.execute(
            select(FailurePattern)
            .where(FailurePattern.project_id == project_id, FailurePattern.pattern_type == pat_key)
            .limit(1)
        )
        existing = existing_r.scalar_one_or_none()
        if existing:
            existing.occurrence_count = (existing.occurrence_count or 1) + 1
            existing.last_occurred_at = datetime.now()
            existing.error_description = (verify_message or '')[:200]
        else:
            db.add(
                FailurePattern(
                    project_id=project_id,
                    pattern_type=pat_key,
                    error_description=(verify_message or '')[:200],
                    occurrence_count=1,
                    root_cause=f'{diag_type}: {(verify_message or "")[:150]}',
                    recovery_suggestion='同类自动修复反复失败，建议人工检查该维度',
                )
            )
        logger.info(f'[PM-Agent 反思] 记录决策失败模式: {pat_key}')
    except Exception as reflect_e:
        logger.debug(f'[PM-Agent 反思] 写失败模式失败（非阻塞）: {reflect_e}')


async def _execute_and_verify(
    db,
    issue: dict[str, Any],
    project_id: str,
    user_id: str,
    decision: str,
    is_lower_risk: bool,
    original_goal: dict[str, Any],
    decision_reason: str,
    diag_type: str,
    scan_round: str,
    severity: str,
    original_message: str,
) -> tuple[dict | None, dict[str, Any]]:
    """Q1 重构：diagnose_and_fix 的「修复 + 验证 + 偏离检查」阶段。

    对于 manual / skip 决策直接产出 early_result（dict），并返回 early_result, {}
    对于 auto_fix 决策返回 None 及 exec_state：
        {fix_action, fix_result, fix_attempted, verified, verified_at, verify_message,
         drift_result, _fix_start_time}
    """
    if decision == 'manual':
        logger.info(f'[PM-Agent 决策 P2] 转人工并记录: type={diag_type} project={project_id[:8]}')
        manual_log_id = None
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
                m_log = await _log_decision(
                    db=db,
                    project_id=project_id,
                    user_id=user_id,
                    issue=issue,
                    severity=severity,
                    decision='manual',
                    decision_reason=decision_reason,
                    fix_action='',
                    fix_result='skipped',
                    fix_attempted=False,
                    verified=False,
                    verified_at=None,
                    verify_message='项目历史成功率过低，等待人工处理',
                    scan_round=scan_round,
                    original_message=original_message,
                    fix_details=None,
                )
                await db.commit()
                manual_log_id = m_log.id if m_log else None
            else:
                await db.rollback()
        except Exception as log_e:
            logger.warning(f'[PM-Agent 决策 P2] 记录 manual 决策失败（非阻塞）: {log_e}')
            await db.rollback()
        result = {
            'type': diag_type,
            'severity': severity,
            'decision': 'manual',
            'fix_action': '',
            'fix_result': 'skipped',
            'fix_attempted': False,
            'verified': False,
            'verify_message': '项目历史成功率过低，等待人工处理',
            'decision_log_id': manual_log_id,
        }
        return result, {}

    if decision != 'auto_fix':
        logger.debug(f'[PM-Agent 决策] 跳过: type={diag_type}（无可用自动修复）')
        result = {
            'type': diag_type,
            'severity': severity,
            'decision': decision,
            'fix_action': '',
            'fix_result': 'skipped',
            'fix_attempted': False,
            'verified': False,
            'verify_message': '',
            'decision_log_id': None,
        }
        return result, {}

    # --- auto_fix: 修复执行 + drift 检查 + 验证 ---
    import time as _time_metric

    fix_start_time = _time_metric.time()
    fix_action = ''
    fix_result = 'skipped'
    fix_attempted = True
    verified = False
    verified_at = None
    verify_message = ''
    try:
        if is_lower_risk:
            issue['_suggestion_only'] = True
        fix_action = await _execute_fix(issue, project_id, user_id, db)
    except Exception as fix_e:
        fix_action = f'修复执行异常: {fix_e}'
        logger.error(
            f'[PM-Agent 决策] 修复失败，项目={project_id}: {fix_e}',
            extra={'project_id': project_id, 'issue_type': issue.get('type', '')},
        )

    drift_result = _check_goal_drift(original_goal, fix_action)
    if drift_result['drift_score'] > 0.6:
        logger.warning(f'[PM-Agent 目标监控] 修复动作偏离原目标: drift_score={drift_result["drift_score"]}, drift_type={drift_result["drift_type"]}')
        try:
            from app.models.pm_diagnostic_log import PMDiagnosticLog

            dup = await db.execute(
                select(func.count())
                .select_from(PMDiagnosticLog)
                .where(
                    PMDiagnosticLog.project_id == project_id,
                    PMDiagnosticLog.diag_type == 'pm_system_alert',
                    PMDiagnosticLog.resolved == False,  # noqa: E712
                    PMDiagnosticLog.created_at >= datetime.now() - timedelta(hours=1),
                )
            )
            if (dup.scalar_one() or 0) == 0:
                db.add(
                    PMDiagnosticLog(
                        project_id=project_id,
                        user_id=user_id,
                        diag_type='pm_system_alert',
                        severity='warning',
                        message=f'[PM-Agent] 修复动作偏离原目标: {drift_result["drift_type"]} (偏离度 {drift_result["drift_score"]:.0%})',
                        suggestion='请检查修复逻辑是否符合预期',
                        resolved=False,
                    )
                )
        except Exception as drift_alert_e:
            logger.debug(f'[PM-Agent 目标监控] 写偏离告警失败（非阻塞）: {drift_alert_e}')

    if fix_action.startswith('修复执行异常'):
        verified = False
        verify_message = fix_action
        fix_result = 'failed'
    else:
        verified, verify_message = await _verify_fix(issue, project_id, user_id, db)
        if verified:
            fix_result = 'success'
            logger.info(f'[PM-Agent 决策] 修复验证通过: {diag_type}')
        else:
            fix_result = 'failed'
            logger.warning(f'[PM-Agent 决策] 修复验证未通过: {diag_type}: {verify_message}')
        # P1-2 量化验证：drift > 0.6 降级为 partial
        if drift_result.get('drift_score', 0) > 0.6 and fix_result == 'success':
            fix_result = 'partial'
            verified = False
            verify_message = f'{verify_message}；修复偏离原目标（drift_score={drift_result["drift_score"]:.0%}）'
            logger.warning(f'[PM-Agent 目标监控] 修复偏离降级: drift_score={drift_result["drift_score"]:.0%} fix_result=partial')
        if not verified and _classify_failure(verify_message) == 'logic':
            try:
                from app.models.pm_diagnostic_log import PMDiagnosticLog
                from sqlalchemy import func as _func2

                dup = await db.execute(
                    select(_func2.count())
                    .select_from(PMDiagnosticLog)
                    .where(
                        PMDiagnosticLog.project_id == project_id,
                        PMDiagnosticLog.diag_type == 'pm_system_alert',
                        PMDiagnosticLog.resolved == False,  # noqa: E712
                        PMDiagnosticLog.created_at >= datetime.now() - timedelta(hours=1),
                    )
                )
                if (dup.scalar_one() or 0) == 0:
                    db.add(
                        PMDiagnosticLog(
                            project_id=project_id,
                            user_id=user_id,
                            diag_type='pm_system_alert',
                            severity='critical',
                            message=f'[PM-Agent] 修复失败: {diag_type}: {(verify_message or "")[:200]}',
                            suggestion='同类修复已进入冷却，请检查代码逻辑或人工处理',
                            resolved=False,
                        )
                    )
            except Exception as alert_e:
                logger.warning(f'[PM-Agent 决策] 写修复失败告警失败（非阻塞）: {alert_e}')

    # L5 反思闭环：failed/partial 均回写失败根因（供下轮决策注入与降级）
    if fix_result in ('failed', 'partial'):
        await _record_decision_failure(db, project_id, diag_type, verify_message)

    verified_at = datetime.now()

    exec_state = {
        'fix_action': fix_action,
        'fix_result': fix_result,
        'fix_attempted': fix_attempted,
        'verified': verified,
        'verified_at': verified_at,
        'verify_message': verify_message,
        'drift_result': drift_result,
        '_fix_start_time': fix_start_time,
    }
    return None, exec_state
