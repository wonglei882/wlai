"""一致性报告查询 API — 外部系统通过此接口获取巡检发现的问题。

端点:
    GET /api/v1/reports — 查询一致性报告
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func

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
    request: Request,
    project_id: str,
    status: str | None = None,
    issue_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """查询一致性报告。

    Args:
        project_id: 项目 ID（必填）
        status: 过滤状态 'unresolved' | 'resolved' | None(全部)
        issue_type: 过滤问题类型
        limit: 分页大小
        offset: 分页偏移
    """
    from app.models.pm_diagnostic_log import PMDiagnosticLog
    from app.database import get_db_session

    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail='未登录或用户 ID 缺失')

    db = await get_db_session(user_id)
    try:
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
    finally:
        await db.close()
