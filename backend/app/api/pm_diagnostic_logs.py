"""PM 诊断日志查询 API"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.pm_diagnostic_log import PMDiagnosticLog
from app.services.pm.pm_time import pm_now

router = APIRouter(prefix='/pm-diagnostic-logs', tags=['PM'])


@router.get('')
async def get_diagnostic_logs(
    project_id: str = Query(..., description='项目ID'),
    resolved: bool = Query(None, description='是否已解决，不传则查全部'),
    diag_type: str = Query(None, description='诊断类型'),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    查询 PM 诊断日志，供前端展示。

    返回格式：
      - 未解决优先，显示 severity + message + suggestion
      - 支持按类型筛选
      - 按创建时间倒序
    """
    where = [PMDiagnosticLog.project_id == project_id]
    if resolved is not None:
        where.append(PMDiagnosticLog.resolved == resolved)
    if diag_type:
        where.append(PMDiagnosticLog.diag_type == diag_type)

    stmt = select(PMDiagnosticLog).where(*where).order_by(PMDiagnosticLog.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    logs = result.scalars().all()

    return {
        'total': len(logs),
        'items': [
            {
                'id': str(log.id),
                'diag_type': log.diag_type,
                'severity': log.severity,
                'message': log.message,
                'suggestion': log.suggestion,
                'chapter_number': log.chapter_number,
                'resolved': log.resolved,
                'resolved_by': log.resolved_by,
                'resolved_at': log.resolved_at.isoformat() if log.resolved_at else None,
                'created_at': log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }


@router.get('/summary')
async def get_diagnostic_summary(
    project_id: str = Query(..., description='项目ID'),
    db: AsyncSession = Depends(get_db),
):
    """诊断汇总：未解决数量 + 各类型统计 + 近7天趋势"""
    # 未解决总数
    total_stmt = select(func.count(PMDiagnosticLog.id)).where(
        PMDiagnosticLog.project_id == project_id,
        ~PMDiagnosticLog.resolved,
    )
    total_res = await db.execute(total_stmt)
    unresolved_total = total_res.scalar() or 0

    # 各类型统计
    type_stmt = (
        select(
            PMDiagnosticLog.diag_type,
            func.count(PMDiagnosticLog.id).label('count'),
        )
        .where(
            PMDiagnosticLog.project_id == project_id,
            ~PMDiagnosticLog.resolved,
        )
        .group_by(PMDiagnosticLog.diag_type)
    )
    type_res = await db.execute(type_stmt)
    type_counts = [{'type': r.diag_type, 'count': r.count} for r in type_res.fetchall()]

    # 严重问题
    critical_stmt = select(func.count(PMDiagnosticLog.id)).where(
        PMDiagnosticLog.project_id == project_id,
        ~PMDiagnosticLog.resolved,
        PMDiagnosticLog.severity == 'critical',
    )
    crit_res = await db.execute(critical_stmt)
    critical_count = crit_res.scalar() or 0

    # 近7天趋势：每日新增 vs 每日解决（含今日，不足7天补0）
    # 批量分组查询，避免循环内逐日查（N+1）
    from datetime import datetime, timedelta
    from sqlalchemy import cast, Date

    days = 7
    today = pm_now().date()
    start_day = today - timedelta(days=days - 1)
    start_dt = datetime(start_day.year, start_day.month, start_day.day)

    # 每日新增数
    created_group_stmt = (
        select(
            cast(PMDiagnosticLog.created_at, Date).label('d'),
            func.count(PMDiagnosticLog.id).label('c'),
        )
        .where(
            PMDiagnosticLog.project_id == project_id,
            PMDiagnosticLog.created_at >= start_dt,
        )
        .group_by(cast(PMDiagnosticLog.created_at, Date))
    )
    created_rows = (await db.execute(created_group_stmt)).fetchall()
    created_by_day = {r.d.isoformat(): r.c for r in created_rows}

    # 每日解决数
    resolved_group_stmt = (
        select(
            cast(PMDiagnosticLog.resolved_at, Date).label('d'),
            func.count(PMDiagnosticLog.id).label('c'),
        )
        .where(
            PMDiagnosticLog.project_id == project_id,
            PMDiagnosticLog.resolved,
            PMDiagnosticLog.resolved_at >= start_dt,
        )
        .group_by(cast(PMDiagnosticLog.resolved_at, Date))
    )
    resolved_rows = (await db.execute(resolved_group_stmt)).fetchall()
    resolved_by_day = {r.d.isoformat(): r.c for r in resolved_rows}

    trend = []
    for i in range(days - 1, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        trend.append(
            {
                'date': day,
                'created': created_by_day.get(day, 0),
                'resolved': resolved_by_day.get(day, 0),
            }
        )

    return {
        'unresolved_total': unresolved_total,
        'critical_count': critical_count,
        'by_type': type_counts,
        'trend': trend,
    }


@router.post('/{log_id}/resolve')
async def resolve_diagnostic_log(
    log_id: str,
    db: AsyncSession = Depends(get_db),
):
    """手动标记诊断日志为已解决（前端用）"""
    stmt = select(PMDiagnosticLog).where(PMDiagnosticLog.id == log_id)
    res = await db.execute(stmt)
    log = res.scalar_one_or_none()
    if not log:
        return {'error': '诊断日志不存在'}
    log.resolved = True
    log.resolved_by = 'user'
    log.resolved_at = pm_now()
    await db.commit()
    return {'ok': True, 'id': str(log.id)}


@router.get('/report')
async def get_fix_report(
    project_id: str = Query(..., description='项目ID'),
    hours: int = Query(2, ge=1, le=72, description='最近 N 小时内的修复记录'),
    db: AsyncSession = Depends(get_db),
):
    """PM 修复报告：最近一轮巡检的修复明细（供前端展示 + 用户认可/驳回）。"""
    from datetime import datetime, timedelta
    from app.models.pm_decision_log import PMDecisionLog

    since = datetime.now() - timedelta(hours=hours)
    stmt = (
        select(PMDecisionLog)
        .where(
            PMDecisionLog.project_id == project_id,
            PMDecisionLog.created_at >= since,
            PMDecisionLog.decision.in_(['auto_fix', 'manual']),
        )
        .order_by(PMDecisionLog.created_at.desc())
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        'total': len(rows),
        'items': [
            {
                'id': str(log.id),
                'diag_type': log.diag_type,
                'severity': log.severity,
                'message': log.original_message,
                'decision': log.decision,
                'fix_action': log.fix_action,
                'fix_result': log.fix_result,
                'verified': log.verified,
                'verify_message': log.verify_message,
                'user_feedback': log.user_feedback,
                'feedback_note': log.feedback_note,
                'created_at': log.created_at.isoformat() if log.created_at else None,
            }
            for log in rows
        ],
    }


@router.post('/{log_id}/feedback')
async def submit_fix_feedback(
    log_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """用户对修复结果反馈：{action: 'approve'|'reject', note: '可选理由'}。

    驳回后该 project+type 的后续同类问题不再自动修（转人工）。
    """
    from datetime import datetime
    from app.models.pm_decision_log import PMDecisionLog

    action = (body or {}).get('action', '')
    note = (body or {}).get('note', '')
    if action not in ('approve', 'reject'):
        return {'error': 'action 必须是 approve 或 reject'}
    stmt = select(PMDecisionLog).where(PMDecisionLog.id == log_id)
    log = (await db.execute(stmt)).scalar_one_or_none()
    if not log:
        return {'error': '决策记录不存在'}
    log.user_feedback = 'approved' if action == 'approve' else 'rejected'
    log.feedback_note = (note or '')[:500]
    log.feedback_at = datetime.now()
    await db.commit()
    return {'ok': True, 'id': str(log.id), 'user_feedback': log.user_feedback}
