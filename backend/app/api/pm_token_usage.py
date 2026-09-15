"""PM Token 使用记录 API

提供 token 消耗查询和统计接口
"""

from datetime import timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.models.pm_token_usage import PMTokenUsage
from app.services.pm.pm_time import pm_now

router = APIRouter(prefix='/api/pm-token-usage', tags=['PM Token Usage'])


class TokenSummary(BaseModel):
    """Token 消耗汇总"""

    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float  # 美元
    by_feature: dict
    by_action: dict


@router.get('/summary')
async def get_token_summary(project_id: str = None, user_id: str = None, days: int = 7, db: AsyncSession = Depends(get_db)):
    """
    获取 Token 消耗汇总

    Args:
        project_id: 项目 ID（可选）
        user_id: 用户 ID（可选）
        days: 统计天数（默认 7 天）
    """
    # 计算时间范围
    start_time = pm_now() - timedelta(days=days)

    # 构建查询
    query = select(PMTokenUsage).where(PMTokenUsage.created_at >= start_time)

    if project_id:
        query = query.where(PMTokenUsage.project_id == project_id)
    if user_id:
        query = query.where(PMTokenUsage.user_id == user_id)

    # 执行查询
    result = await db.execute(query)
    records = result.scalars().all()

    # 汇总统计
    total_tokens = sum(r.total_tokens or 0 for r in records)
    prompt_tokens = sum(r.prompt_tokens or 0 for r in records)
    completion_tokens = sum(r.completion_tokens or 0 for r in records)
    cost_usd = sum(r.cost_usd or 0 for r in records) / 1_000_000  # 微美元 → 美元

    # 按功能分类
    by_feature = {}
    for r in records:
        feature = r.feature or 'unknown'
        by_feature[feature] = by_feature.get(feature, 0) + (r.total_tokens or 0)

    # 按操作分类
    by_action = {}
    for r in records:
        action = r.action or 'unknown'
        by_action[action] = by_action.get(action, 0) + (r.total_tokens or 0)

    return {
        'success': True,
        'summary': {
            'total_tokens': total_tokens,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'cost_usd': cost_usd,
            'by_feature': by_feature,
            'by_action': by_action,
            'record_count': len(records),
            'days': days,
        },
    }


@router.get('/trend')
async def get_token_trend(project_id: str = None, user_id: str = None, days: int = 7, db: AsyncSession = Depends(get_db)):
    """
    获取 Token 消耗趋势（按天分组）
    """
    start_time = pm_now() - timedelta(days=days)

    # 构建查询
    query = (
        select(
            func.date(PMTokenUsage.created_at).label('date'),
            func.sum(PMTokenUsage.total_tokens).label('total_tokens'),
            func.sum(PMTokenUsage.cost_usd).label('cost_usd'),
            func.count(PMTokenUsage.id).label('count'),
        )
        .where(PMTokenUsage.created_at >= start_time)
        .group_by(func.date(PMTokenUsage.created_at))
        .order_by(func.date(PMTokenUsage.created_at))
    )

    if project_id:
        query = query.where(PMTokenUsage.project_id == project_id)
    if user_id:
        query = query.where(PMTokenUsage.user_id == user_id)

    result = await db.execute(query)
    rows = result.all()

    trend = []
    for row in rows:
        trend.append(
            {
                'date': str(row.date),
                'total_tokens': row.total_tokens or 0,
                'cost_usd': (row.cost_usd or 0) / 1_000_000,
                'count': row.count,
            }
        )

    return {
        'success': True,
        'trend': trend,
        'days': days,
    }


@router.get('/top-cost')
async def get_top_cost(limit: int = 10, days: int = 7, db: AsyncSession = Depends(get_db)):
    """
    获取消耗最高的项目/用户
    """
    start_time = pm_now() - timedelta(days=days)

    # 按项目汇总
    project_query = (
        select(PMTokenUsage.project_id, func.sum(PMTokenUsage.total_tokens).label('total_tokens'), func.sum(PMTokenUsage.cost_usd).label('cost_usd'))
        .where(PMTokenUsage.created_at >= start_time)
        .group_by(PMTokenUsage.project_id)
        .order_by(func.sum(PMTokenUsage.total_tokens).desc())
        .limit(limit)
    )

    project_result = await db.execute(project_query)
    top_projects = [
        {
            'project_id': row.project_id,
            'total_tokens': row.total_tokens,
            'cost_usd': (row.cost_usd or 0) / 1_000_000,
        }
        for row in project_result.all()
    ]

    return {
        'success': True,
        'top_projects': top_projects,
    }