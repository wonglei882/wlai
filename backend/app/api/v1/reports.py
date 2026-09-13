"""一致性报告查询 API — 外部系统通过此接口获取巡检发现的问题。

端点:
    GET /api/v1/reports — 查询一致性报告
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_db_session_depends

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/reports', tags=['consistency-agent'])


# =============================================================================
# 响应模型
# =============================================================================


class ReportItem(BaseModel):
    """单条报告项。"""

    id: str
    issue_type: str
    severity: str = 'warning'
    message: str = ''
    segments: list[int] = Field(default_factory=list, description='关联的序列号列表')
    suggestion: str = ''
    created_at: str = ''
    resolved: bool = False


class ReportsResponse(BaseModel):
    """报告查询响应。"""

    reports: list[ReportItem]
    total: int
    project_id: str


# =============================================================================
# 端点
# =============================================================================


@router.get('', response_model=ReportsResponse)
async def get_reports(
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
    project_id: str = None,
    status: str | None = None,
    issue_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """查询一致性报告。"""
    from app.models.pm_diagnostic_log import PMDiagnosticLog

    # 基础查询
    query = select(PMDiagnosticLog).where(
        PMDiagnosticLog.project_id == project_id,
        PMDiagnosticLog.user_id == user_id,
    )

    # 状态过滤
    if status == 'unresolved':
        query = query.where(PMDiagnosticLog.resolved.is_(False))
    elif status == 'resolved':
        query = query.where(PMDiagnosticLog.resolved.is_(True))

    # 类型过滤
    if issue_type:
        query = query.where(PMDiagnosticLog.diag_type == issue_type)

    # 总数
    count_query = select(func.count()).select_from(PMDiagnosticLog).where(
        PMDiagnosticLog.project_id == project_id,
        PMDiagnosticLog.user_id == user_id,
    )
    if status == 'unresolved':
        count_query = count_query.where(PMDiagnosticLog.resolved.is_(False))
    elif status == 'resolved':
        count_query = count_query.where(PMDiagnosticLog.resolved.is_(True))
    if issue_type:
        count_query = count_query.where(PMDiagnosticLog.diag_type == issue_type)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页查询
    query = query.order_by(PMDiagnosticLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)

    reports = []
    for dl in result.scalars().all():
        reports.append(
            ReportItem(
                id=str(dl.id),
                issue_type=dl.diag_type or '',
                severity=dl.severity or 'warning',
                message=dl.message or '',
                segments=[dl.chapter_number] if dl.chapter_number else [],
                suggestion=dl.suggestion or '',
                created_at=str(dl.created_at or ''),
                resolved=bool(dl.resolved),
            )
        )

    return ReportsResponse(reports=reports, total=total, project_id=project_id)
