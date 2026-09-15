"""
PM API — 用户可见的 PM Agent 决策记录端点

提供：
- GET  /api/pm/decisions        — 查看最近决策记录
- GET  /api/pm/decisions/{id}   — 查看单条决策详情
- POST /api/pm/decisions/{id}/dismiss — 用户手动确认/关闭
- POST /api/pm/rerun            — 手动触发一轮全量 PM Agent 决策
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc, func as sa_func

from app.database import get_db
from app.core.exceptions import SystemException
import logging
from app.models.pm_decision_log import PMDecisionLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/pm', tags=['PM Agent'])

# sentinel：判断 verified 参数是否被调用方显式提供
_VERIFIED_SENTINEL = Query(None, description='按验证状态筛选')


async def _validate_project_ownership(db, project_id: str, user_id: str) -> None:
    """校验 project_id 归属 user_id，不匹配则抛 403。"""
    from app.models.project import Project

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail='项目不存在')
    if project.user_id != user_id:
        raise HTTPException(status_code=403, detail='无权访问此项目 PM 数据')


# =============================================================================
# GET /api/pm/decisions — 最近决策记录
# =============================================================================

# sentinel：判断参数是否被调用方显式提供
_SENTINEL_STR = Query(None)


@router.get('/decisions')
async def list_decisions(
    project_id: str | None = _SENTINEL_STR,
    decision: str | None = _SENTINEL_STR,
    result: str | None = _SENTINEL_STR,
    verified: bool | None = _VERIFIED_SENTINEL,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
):
    """查看 PM Agent 的决策历史。"""
    query = select(PMDecisionLog).order_by(desc(PMDecisionLog.created_at))

    if project_id is not None and project_id is not _SENTINEL_STR:
        query = query.where(PMDecisionLog.project_id == project_id)
    if decision is not None and decision is not _SENTINEL_STR:
        query = query.where(PMDecisionLog.decision == decision)
    if result is not None and result is not _SENTINEL_STR:
        query = query.where(PMDecisionLog.fix_result == result)
    if verified is not None and verified is not _VERIFIED_SENTINEL:
        query = query.where(PMDecisionLog.verified == verified)

    # 计数：复用过滤条件
    count_query = select(sa_func.count(PMDecisionLog.id))
    if project_id is not None and project_id is not _SENTINEL_STR:
        count_query = count_query.where(PMDecisionLog.project_id == project_id)
    if decision is not None and decision is not _SENTINEL_STR:
        count_query = count_query.where(PMDecisionLog.decision == decision)
    if result is not None and result is not _SENTINEL_STR:
        count_query = count_query.where(PMDecisionLog.fix_result == result)
    if verified is not None and verified is not _VERIFIED_SENTINEL:
        count_query = count_query.where(PMDecisionLog.verified == verified)
    total = (await db.execute(count_query)).scalar() or 0

    query = query.offset(offset).limit(limit)
    rows = (await db.execute(query)).scalars().all()

    return {
        'total': total,
        'offset': offset,
        'limit': limit,
        'items': [r.to_summary() for r in rows],
    }


# =============================================================================
# GET /api/pm/decisions/{id} — 单条决策详情
# =============================================================================


@router.get('/decisions/{decision_id}')
async def get_decision(decision_id: str, db=Depends(get_db)):
    """查看单条 PM Agent 决策详情（含监督层审核报告）。"""
    log = (await db.execute(select(PMDecisionLog).where(PMDecisionLog.id == decision_id))).scalar_one_or_none()

    if not log:
        raise HTTPException(status_code=404, detail='决策记录不存在')

    # fix_details 解析为 dict（含 audit_report 审核报告），解析失败返回原始字符串
    try:
        import json as _json

        fix_details = _json.loads(log.fix_details) if log.fix_details else None
    except Exception:
        fix_details = log.fix_details if log.fix_details else None

    # 监督层审核报告提到顶层（前端审核面板直接消费）
    audit_report = None
    if isinstance(fix_details, dict):
        audit_report = fix_details.get('audit_report')

    return {
        'id': log.id,
        'project_id': log.project_id,
        'user_id': log.user_id,
        'diag_type': log.diag_type,
        'chapter_number': log.chapter_number,
        'severity': log.severity,
        'original_message': log.original_message,
        'decision': log.decision,
        'decision_reason': log.decision_reason,
        'fix_action': log.fix_action,
        'fix_result': log.fix_result,
        'fix_attempted': log.fix_attempted,
        'verified': log.verified,
        'verified_at': str(log.verified_at) if log.verified_at else None,
        'verify_message': log.verify_message,
        'fix_details': fix_details,
        'audit_report': audit_report,
        'user_feedback': log.user_feedback,
        'feedback_note': log.feedback_note or '',
        'feedback_at': str(log.feedback_at) if log.feedback_at else None,
        'scan_round': log.scan_round,
        'created_at': str(log.created_at) if log.created_at else None,
    }


# =============================================================================
# POST /api/pm/decisions/{id}/dismiss — 用户确认/关闭
# =============================================================================


@router.post('/decisions/{decision_id}/dismiss')
async def dismiss_decision(decision_id: str, db=Depends(get_db)):
    """用户手动确认决策结果并关闭。"""
    log = (await db.execute(select(PMDecisionLog).where(PMDecisionLog.id == decision_id))).scalar_one_or_none()

    if not log:
        raise HTTPException(status_code=404, detail='决策记录不存在')

    log.verified = True
    log.verified_at = datetime.now()
    log.verify_message = '用户手动确认'
    log.updated_at = datetime.now()
    await db.commit()

    return {'status': 'ok', 'id': decision_id, 'verified': True}


# =============================================================================
# POST /api/pm/decisions/{id}/feedback — 用户反馈（approve/reject）
# P2: 提升 5479 条决策的用户参与度（当前仅 1 条 feedback）
# =============================================================================


@router.post('/decisions/{decision_id}/feedback')
async def feedback_decision(
    decision_id: str,
    feedback: str = Query(..., description='approved 或 rejected'),
    comment: str | None = Query(None, description='用户备注'),
    db=Depends(get_db),
):
    """用户对 PM Agent 决策结果反馈（approve/reject）。

    - approved: 标记决策已采纳，后续同类问题不再重复修复
    - rejected: 标记决策被驳回，下次同类问题转人工处理（manual 状态）
    """
    if feedback not in ('approved', 'rejected'):
        raise HTTPException(status_code=400, detail="feedback 必须是 'approved' 或 'rejected'")

    log = (await db.execute(select(PMDecisionLog).where(PMDecisionLog.id == decision_id))).scalar_one_or_none()

    if not log:
        raise HTTPException(status_code=404, detail='决策记录不存在')

    # 写入 user_feedback 字段（PMDecisionLog 已有 user_feedback/feedback_note/feedback_at）
    log.user_feedback = feedback
    log.feedback_note = comment or ''
    log.feedback_at = datetime.now()
    log.updated_at = datetime.now()

    # rejected → 标记该维度后续转人工
    if feedback == 'rejected':
        log.verify_message = f'用户驳回: {comment or "无说明"}，后续同类问题转人工'
    else:
        log.verified = True
        log.verified_at = datetime.now()
        log.verify_message = '用户确认采纳'

    await db.commit()

    # 自进化：用户驳回 → 学习排除规则（非阻塞，失败不影响反馈写入）
    if feedback == 'rejected':
        try:
            from app.services.pm.pm_evolution import learn_from_rejection

            await learn_from_rejection(db, log)
        except Exception as learn_err:
            logger.warning(f'[PM] 驳回学习失败（非阻塞）: {learn_err}')

    return {'status': 'ok', 'id': decision_id, 'feedback': feedback}


# =============================================================================
# POST /api/pm/rerun — 手动触发全量决策
# =============================================================================


@router.post('/rerun')
async def trigger_rerun():
    """手动触发一轮全量 PM Agent 巡检 + 决策 + 修复 + 验证。"""
    try:
        from app.services.pm.pm_api import scan_all_projects

        result = await scan_all_projects()

        total_projects = len(result)
        total_issues = 0
        total_decisions = 0
        for _pid, scan_result in result.items():
            issues = scan_result.get('issues', {})
            decisions = scan_result.get('decisions', [])
            total_issues += sum(len(v) for v in issues.values())
            total_decisions += len(decisions)

        return {
            'status': 'ok',
            'projects_scanned': total_projects,
            'issues_found': total_issues,
            'decisions_made': total_decisions,
        }
    except Exception as e:
        logger.warning('[PM-Agent API] 手动触发巡检异常: %s', e)
        raise SystemException('巡检触发失败') from e


# =============================================================================
# 主动巡检 API（P2）
# =============================================================================


@router.get('/inspect/{project_id}', summary='主动巡检 — 检查项目 PM 健康状态')
async def proactive_inspect(
    project_id: str,
    user_id: str = Query(..., description='用户ID'),
    db=Depends(get_db),
):
    """
    对指定项目执行 PM Agent 主动巡检。

    检查四个维度：
    1. 低质量决策（PMDecisionLog quality_score < 5）
    2. 高频失败模式（pm_failure_patterns occurrence_count >= 3）
    3. 世界观 drift（PMConsistencyState.world_states.drift_detected）
    4. 悬而未决的决策（unresolved=True）

    返回巡检报告，包含健康分、问题列表、警告列表、建议。
    """
    from app.services.pm.pm_proactive_inspector import run_proactive_inspection

    await _validate_project_ownership(db, project_id, user_id)
    try:
        report = await run_proactive_inspection(db, project_id, user_id)
        return {
            'status': 'ok',
            'report': report,
        }
    except Exception as e:
        logger.warning('[PM巡检] API 调用失败: %s', e)
        raise SystemException('巡检失败') from e


# =============================================================================
# 主动汇报 API（on-demand）— 让前端可随时拉取预警报告与主动建议
# 之前 ProactiveReporter.check() / generate_proactive_suggestions() 仅后台巡检
# 触发；本组端点提供前端按需拉取入口。
# =============================================================================


@router.get('/proactive-report/{project_id}', summary='主动汇报器 — 生成预警报告')
async def get_proactive_report(
    project_id: str,
    user_id: str = Query(..., description='用户ID'),
    db=Depends(get_db),
):
    """对指定项目运行一次主动汇报器检查，返回预警报告。

    聚合 LongNovelGuardian 扫描结果 + OOC 未解决违规，输出 critical/high 预警。
    """
    await _validate_project_ownership(db, project_id, user_id)
    try:
        from app.services.proactive_reporter import reporter

        report = await reporter.check(project_id, user_id, db)
        return {'status': 'ok', 'report': report.to_response()}
    except Exception as e:
        logger.warning('[PM] 主动汇报器 API 调用失败: %s', e)
        raise SystemException('主动汇报器调用失败') from e


@router.get('/suggestions/{project_id}', summary='主动建议 — 生成写作建议')
async def get_proactive_suggestions(
    project_id: str,
    user_id: str = Query(..., description='用户ID'),
    db=Depends(get_db),
):
    """对指定项目生成主动写作建议（内容偏短/伏笔过多/主角缺场/字数下降）。"""
    await _validate_project_ownership(db, project_id, user_id)
    try:
        from app.services.proactive_suggestions import generate_proactive_suggestions

        suggestions = await generate_proactive_suggestions(project_id, db)
        return {'status': 'ok', 'suggestions': suggestions, 'total': len(suggestions)}
    except Exception as e:
        logger.warning('[PM] 主动建议 API 调用失败: %s', e)
        raise SystemException('主动建议调用失败') from e


# =============================================================================
# 自主度配置 API（G1）
# =============================================================================


@router.get('/autonomy/{project_id}', summary='获取 PM Agent 自主度配置')
async def get_autonomy_config(
    project_id: str,
    user_id: str = Query(..., description='用户ID'),
    db=Depends(get_db),
):
    """获取当前项目的 PM Agent 自主度配置。"""
    from app.models import PMAutonomyConfig
    from sqlalchemy import select

    await _validate_project_ownership(db, project_id, user_id)

    result = await db.execute(
        select(PMAutonomyConfig).where(
            PMAutonomyConfig.project_id == project_id,
            PMAutonomyConfig.user_id == user_id,
        )
    )
    config = result.scalar_one_or_none()

    if config:
        return {
            'status': 'ok',
            'level': config.level,
            'level_cn': config.level_cn,
            'confidence_threshold': config.confidence_threshold,
            'auto_execute_types': config.auto_execute_types.split(','),
        }

    # 默认配置
    return {
        'status': 'ok',
        'level': 'advisor',
        'level_cn': '建议模式',
        'confidence_threshold': 0.6,
        'auto_execute_types': ['outline', 'suggest', 'foreshadow', 'character', 'world_setting'],
    }


@router.post('/autonomy/{project_id}', summary='设置 PM Agent 自主度配置')
async def set_autonomy_config(
    project_id: str,
    user_id: str = Query(..., description='用户ID'),
    level: str = Query(..., description='级别: advisor | advisor_plus | autonomous'),
    confidence_threshold: float = Query(0.6, ge=0.0, le=1.0),
    auto_execute_types: str = Query('outline,suggest,foreshadow,character,world_setting'),
    db=Depends(get_db),
):
    """设置 PM Agent 自主度配置。"""
    from app.models import PMAutonomyConfig
    from sqlalchemy import select
    import uuid

    await _validate_project_ownership(db, project_id, user_id)

    valid_levels = {'advisor', 'advisor_plus', 'autonomous'}
    if level not in valid_levels:
        raise HTTPException(
            status_code=400,
            detail=f'无效级别，可选: {valid_levels}',
        )

    result = await db.execute(
        select(PMAutonomyConfig).where(
            PMAutonomyConfig.project_id == project_id,
            PMAutonomyConfig.user_id == user_id,
        )
    )
    config = result.scalar_one_or_none()

    if config:
        config.level = level
        config.confidence_threshold = confidence_threshold
        config.auto_execute_types = auto_execute_types
    else:
        config = PMAutonomyConfig(
            id=str(uuid.uuid4()),
            project_id=project_id,
            user_id=user_id,
            level=level,
            confidence_threshold=confidence_threshold,
            auto_execute_types=auto_execute_types,
        )
        db.add(config)

    await db.commit()
    logger.info(f'[PM自主度] user={user_id[:8]} project={project_id[:8]} level={level}')

    return {
        'status': 'ok',
        'level': level,
        'confidence_threshold': confidence_threshold,
        'auto_execute_types': auto_execute_types.split(','),
    }


# =============================================================================
# G2: 澄清问题答案 API
# =============================================================================


@router.post('/clarify/{project_id}', summary='提交澄清问题的用户答案')
async def submit_clarification(
    project_id: str,
    user_id: str = Query(..., description='用户ID'),
    tool_name: str = Query(..., description='工具名'),
    action: str = Query(..., description='用户选择的操作: execute | preview | skip'),
    db=Depends(get_db),
):
    """
    用户在澄清问题中选择后，PM Agent 执行对应操作。
    action:
    - execute: 执行该工具
    - preview: 仅展示变更预览
    - skip:    跳过，不执行
    """
    await _validate_project_ownership(db, project_id, user_id)
    from app.services.project_manager_service import CommandRegistry
    from app.agent.core.command_executor import CommandExecutor

    if action == 'skip':
        return {'status': 'ok', 'message': '已跳过'}

    # 构造命令
    cmd_text = f'[TOOL:{tool_name}|project_id={project_id}]'
    registry = CommandRegistry()
    executor = CommandExecutor(
        registry=registry,
        db=db,
        user_id=user_id,
        project_id=project_id,
    )

    try:
        raw_results = await executor.execute_text(cmd_text)
        logs = [r.logs for r in raw_results if r.logs]
        return {
            'status': 'ok',
            'action': action,
            'tool_name': tool_name,
            'result': '\n'.join(logs[0]) if logs else '执行完成',
        }
    except Exception as e:
        logger.warning('[PM澄清] 执行失败: %s', e)
        raise SystemException('执行失败') from e


# =============================================================================
# G3: PM 诊断面板 API（前端可视化）
# =============================================================================


@router.get('/dashboard/{project_id}', summary='PM 诊断面板数据')
async def get_pm_dashboard(
    project_id: str,
    user_id: str = Query(..., description='用户ID'),
    db=Depends(get_db),
):
    """
    返回结构化的 PM 诊断数据，供前端可视化面板使用。
    包含：伏笔逾期/冲突密度/大纲健康度/一致性趋势/角色弧光/情感流向
    """
    await _validate_project_ownership(db, project_id, user_id)
    from app.services.inspiration_sub.diagnostic import (
        _track_foreshadow_recovery,
        _analyze_conflict_density,
        _score_outline_health,
        _analyze_consistency_trend,
        _track_character_arc,
        _analyze_emotion_flow,
        _get_cached_diagnostic,
    )

    # 缓存检测（跳过六大诊断，直接返回）
    cached_text, is_valid = await _get_cached_diagnostic(db, project_id)
    cache_status = 'hit' if is_valid else 'miss'

    # 并行执行六大诊断
    foreshadows_task = _track_foreshadow_recovery(db, project_id)
    conflicts_task = _analyze_conflict_density(db, project_id)
    outline_task = _score_outline_health(project_id, db)
    trend_task = _analyze_consistency_trend(db, project_id)
    arcs_task = _track_character_arc(db, project_id)
    emotion_task = _analyze_emotion_flow(db, project_id)

    foreshadows, conflicts, outline, trend, arcs, emotion = await asyncio.gather(
        foreshadows_task,
        conflicts_task,
        outline_task,
        trend_task,
        arcs_task,
        emotion_task,
    )

    # 综合健康分（0-10）
    health_score = 10
    issues = []
    warnings = []

    # 伏笔逾期扣分
    critical_fs = [f for f in foreshadows if f.get('urgency') == 'critical']
    warning_fs = [f for f in foreshadows if f.get('urgency') == 'warning']
    if critical_fs:
        health_score -= 2
        issues.append({'type': '伏笔逾期', 'severity': 'critical', 'count': len(critical_fs), 'items': critical_fs})
    if warning_fs:
        health_score -= 0.5
        warnings.append({'type': '伏笔待处理', 'severity': 'warning', 'count': len(warning_fs), 'items': warning_fs})

    # 冲突薄弱扣分
    weak_conflicts = [c for c in conflicts if c.get('level') in ('weak', 'low')]
    if weak_conflicts:
        health_score -= 0.5 * min(2, len(weak_conflicts))
        warnings.append({'type': '冲突薄弱', 'severity': 'warning', 'count': len(weak_conflicts), 'items': weak_conflicts})

    # 大纲健康度
    if outline.get('score') is not None:
        health_score = min(health_score, outline['score'])
        if outline['score'] < 6:
            issues.append({'type': '大纲健康度', 'severity': 'critical', 'score': outline['score'], 'items': outline.get('issues', [])})
        elif outline['score'] < 8:
            warnings.append({'type': '大纲健康度', 'severity': 'warning', 'score': outline['score'], 'items': outline.get('issues', [])})

    # 一致性趋势恶化
    if trend.get('direction') == 'worsening':
        health_score -= 1
        warnings.append({'type': '一致性恶化', 'severity': 'warning', 'direction': trend['direction'], 'total': trend.get('total', 0)})

    # 角色弧光薄弱
    weak_arcs = [a for a in arcs if a.get('status') in ('weak', 'flat')]
    if weak_arcs:
        health_score -= 0.5
        warnings.append({'type': '角色弧光薄弱', 'severity': 'warning', 'count': len(weak_arcs), 'items': weak_arcs})

    # 情感单调预警
    if emotion.get('flat_warning'):
        health_score -= 0.3
        warnings.append({'type': '情感单调', 'severity': 'warning', 'detail': emotion['flat_warning']})

    health_score = float(max(0.0, round(health_score, 1)))

    return {
        'status': 'ok',
        'project_id': project_id,
        'health_score': health_score,
        'health_level': '🟢良好' if health_score >= 8 else '🟡一般' if health_score >= 6 else '🔴需关注',
        'cache_status': cache_status,
        'issues': issues,
        'warnings': warnings,
        'details': {
            'foreshadows': {'critical': critical_fs, 'warning': warning_fs, 'total': len(foreshadows)},
            'conflicts': {'weak': weak_conflicts, 'total': len(conflicts)},
            'outline': outline,
            'trend': trend,
            'arcs': arcs[:5],
            'emotion': emotion,
        },
    }

# =============================================================================
# 自进化 API（E5）— 阈值进化 / 排除规则 / 事件日志
# =============================================================================


@router.get('/evolution', summary='PM 自进化总览')
async def get_evolution(
    project_id: str | None = Query(None, description='按项目筛选'),
    db=Depends(get_db),
):
    """返回自进化状态总览（各维度信号/运行时阈值/节流）。"""
    from app.services.pm.pm_evolution import get_evolution_overview

    return await get_evolution_overview(db, project_id)


@router.get('/evolution/events', summary='PM 自进化事件日志')
async def get_evolution_events(
    limit: int = Query(50, ge=1, le=200),
    db=Depends(get_db),
):
    from app.services.pm.pm_evolution import list_evolution_events

    return {'items': await list_evolution_events(db, limit)}


@router.get('/evolution/rules', summary='PM 排除规则列表')
async def get_evolution_rules(
    project_id: str | None = Query(None, description='按项目筛选'),
    dimension: str | None = Query(None, description='按维度筛选'),
    db=Depends(get_db),
):
    from app.services.pm.pm_evolution import list_exclusion_rules

    return {'items': await list_exclusion_rules(db, project_id, dimension)}


@router.post('/evolution/trigger', summary='手动触发一轮进化')
async def trigger_evolution(db=Depends(get_db)):
    """对所有有进化状态的项目立即执行一轮信号聚合与阈值进化。"""
    from app.services.pm.pm_evolution import run_evolution_now

    return await run_evolution_now(db)


@router.post('/evolution/{project_id}/reset', summary='重置项目自进化状态')
async def reset_evolution(project_id: str, db=Depends(get_db)):
    """重置项目的进化状态/排除规则/事件，并清空运行时覆盖缓存。"""
    from app.services.pm.pm_evolution import reset_project_evolution

    deleted = await reset_project_evolution(db, project_id)
    return {'status': 'ok', 'project_id': project_id, 'deleted_states': deleted}