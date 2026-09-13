"""异步任务 API — 后台任务状态查询。

端点:
    GET  /api/v1/tasks              — 任务列表
    GET  /api/v1/tasks/{task_id}    — 任务详情
    POST /api/v1/tasks/{task_id}/cancel — 取消任务
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_db_session_depends
from app.core.exceptions import NotFoundError, ConflictError
from app.models.task import AsyncTask

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/tasks', tags=['consistency-agent'])


class TaskResponse(BaseModel):
    id: str
    project_id: str
    task_type: str
    status: str
    progress: float = 0.0
    result: dict | list = {}
    error: str = ''
    created_at: str = ''
    updated_at: str = ''



class TaskCreateRequest(BaseModel):
    project_id: str
    task_type: str  # storyboard_gen / image_gen / video_gen / voice_gen / prompt_compile
    payload: dict = {}


@router.post('')
async def create_task(
    req: TaskCreateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """创建并异步执行任务（当前支持 image_gen，其余类型提示未接入）。"""
    from app.services.task_runner import submit_task

    task = AsyncTask(
        project_id=req.project_id,
        user_id=user_id,
        task_type=req.task_type,
        status='pending',
        progress=0.0,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    if req.task_type == 'image_gen':
        shot_id = (req.payload or {}).get('shot_id')
        if not shot_id:
            raise HTTPException(status_code=400, detail='image_gen 需要 payload.shot_id')
        from app.services.comic.generation_tasks import _run_image_generation

        platform = (req.payload or {}).get('platform', 'midjourney')
        provider = (req.payload or {}).get('provider', 'mock')
        submit_task(
            task,
            lambda: _run_image_generation(shot_id, user_id, platform, provider),
        )
        return {'id': task.id, 'status': 'pending', 'message': '出图任务已提交'}

    task.status = 'failed'
    task.error = f'任务类型 {req.task_type} 暂未接入'
    await db.commit()
    raise HTTPException(status_code=400, detail=f'任务类型 {req.task_type} 暂未接入')

@router.get('')
async def list_tasks(
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
):
    """查询任务列表。"""
    query = select(AsyncTask).where(AsyncTask.user_id == user_id)
    if project_id:
        query = query.where(AsyncTask.project_id == project_id)
    if status:
        query = query.where(AsyncTask.status == status)
    query = query.order_by(AsyncTask.created_at.desc()).limit(limit)

    result = await db.execute(query)
    tasks = result.scalars().all()
    return {
        'tasks': [
            {
                'id': t.id,
                'project_id': t.project_id,
                'task_type': t.task_type,
                'status': t.status,
                'progress': t.progress,
                'error': t.error or '',
                'created_at': t.created_at.isoformat() if t.created_at else '',
            }
            for t in tasks
        ],
        'total': len(tasks),
    }


@router.get('/{task_id}')
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """查询任务详情。"""
    result = await db.execute(
        select(AsyncTask).where(
            AsyncTask.id == task_id,
            AsyncTask.user_id == user_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise NotFoundError('任务', task_id)
    return {
        'id': task.id,
        'project_id': task.project_id,
        'task_type': task.task_type,
        'status': task.status,
        'progress': task.progress,
        'result': task.result or {},
        'error': task.error or '',
        'created_at': task.created_at.isoformat() if task.created_at else '',
        'updated_at': task.updated_at.isoformat() if task.updated_at else '',
    }


@router.post('/{task_id}/cancel')
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """取消任务。"""
    result = await db.execute(
        select(AsyncTask).where(
            AsyncTask.id == task_id,
            AsyncTask.user_id == user_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise NotFoundError('任务', task_id)
    if task.status in ('completed', 'failed'):
        raise ConflictError('任务已结束')

    task.status = 'failed'
    task.error = '用户取消'
    await db.commit()
    return {'id': task.id, 'status': 'failed', 'message': '任务已取消'}
