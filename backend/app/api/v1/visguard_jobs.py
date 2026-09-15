"""VisGuard 异步任务 API — 云端生图任务（202 提交 + SSE 订阅）。

端点:
    POST /api/v1/visguard/jobs                    — 提交生图任务（202 Accepted）
    GET  /api/v1/visguard/jobs/{job_id}           — 任务详情
    GET  /api/v1/visguard/jobs/{job_id}/events    — SSE 进度订阅（终态后自动关闭）
    POST /api/v1/visguard/jobs/{job_id}/cancel    — 取消任务

设计（v2：长任务一律异步化）：
- 依据能力矩阵：generate_backend='none' 时创建请求立即 503（客户端感知不可用），
  不产生僵尸任务；后端配置后创建 202 + job_id，worker 在 task_runner 执行。
- 任务行复用 AsyncTask（task_type='visguard_generate'），进度经 DB 落盘，
  并同步广播到 /ws/tasks/{job_id}（ws.py 已接线 task_runner）。
- SSE 轮询 DB（1s 间隔）推送 pending/running -> completed/failed；客户端断开自动停止。
"""

import asyncio
import base64
import json
import logging
from dataclasses import fields

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_db_session_depends
from app.api.v1.visguard import _owned_project
from app.services.task_runner import get_running_task, submit_task
from app.services.visguard.core.artifact import Artifact, GenerationResult
from app.services.visguard.core.exceptions import BackendNotConfiguredError, VisGuardError
from app.services.visguard.generation.base import GenerationParams
from app.services.visguard.generation.factory import create_generator

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/visguard', tags=['visguard'])


class VisGuardJobCreateRequest(BaseModel):
    """生图任务参数（供应商无关，适配器内部映射）。"""

    project_id: str
    prompt: str = Field(..., min_length=1, max_length=4000)
    negative_prompt: str = ''
    width: int = Field(256, ge=256, le=2048)
    height: int = Field(256, ge=256, le=2048)
    steps: int = Field(20, ge=1, le=100)
    cfg: float = Field(7.0, ge=0.0, le=30.0)
    seed: int | None = None
    character_ids: list[str] = Field(default_factory=list)
    control_type: str | None = None
    control_weight: float = Field(0.8, ge=0.0, le=1.0)
    provider: str = ''
    model: str = ''


def _artifact_to_dict(a: Artifact) -> dict:
    """Artifact → JSON 安全 dict（bytes 数据以 base64 保留，避免任务 result JSON 列报错）。"""
    data = a.data
    if isinstance(data, bytes):
        data = base64.b64encode(data).decode('ascii')
    return {'type': a.type, 'format': a.format, 'data': data, 'metadata': a.metadata}


def _generation_result_to_dict(r: GenerationResult) -> dict:
    """GenerationResult → JSON 安全 dict（供任务 result 列 / SSE 使用）。"""
    return {
        'artifacts': [_artifact_to_dict(a) for a in r.artifacts],
        'duration_ms': r.duration_ms,
        'provider': r.provider,
        'model': r.model,
        'warnings': list(r.warnings),
    }


async def _run_visguard_generation(params: dict) -> dict:
    """生成任务 worker（task_runner 调用）：能力 → 生成器 → 统一结果。"""
    generator = create_generator()
    if generator is None:
        raise BackendNotConfiguredError(
            '生成后端未配置（visguard_generate_backend=none）'
        )
    # 仅透传 GenerationParams 已知字段（过滤不规则入参）
    allowed = {f.name for f in fields(GenerationParams)}
    clean = {k: v for k, v in params.items() if k in allowed}
    result = await generator.generate(GenerationParams(**clean))
    return _generation_result_to_dict(result)


def _map_job_error(e: VisGuardError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


# =============================================================================
# POST /jobs — 提交生图任务（202）
# =============================================================================

@router.post('/jobs', status_code=202)
async def create_visguard_job(
    req: VisGuardJobCreateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """提交生图任务。

    Returns 202 + job_id；随后通过 GET /jobs/{job_id}/events（SSE）订阅进度。
    能力矩阵 generate 关闭时返回 503（不等异步失败，客户端立即感知不可用）。
    """
    await _owned_project(req.project_id, db, user_id)
    generator = create_generator()
    if generator is None:
        raise _map_job_error(
            BackendNotConfiguredError('生成后端未配置（visguard_generate_backend=none）')
        )

    from app.models.task import AsyncTask

    task = AsyncTask(
        project_id=req.project_id,
        user_id=user_id,
        task_type='visguard_generate',
        status='pending',
        progress=0.0,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    payload = req.model_dump()
    submit_task(task, lambda: _run_visguard_generation(payload))
    return {
        'job_id': task.id,
        'status': 'pending',
        'message': '生图任务已提交，GET /api/v1/visguard/jobs/{job_id}/events 订阅进度',
    }


# =============================================================================
# GET /jobs/{job_id} — 任务详情
# =============================================================================

async def _get_owned_task(job_id: str, db: AsyncSession, user_id: str):
    from app.models.task import AsyncTask

    result = await db.execute(
        select(AsyncTask).where(
            AsyncTask.id == job_id,
            AsyncTask.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


@router.get('/jobs/{job_id}')
async def get_visguard_job(
    job_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """查询生图任务详情。"""
    task = await _get_owned_task(job_id, db, user_id)
    if task is None:
        raise HTTPException(status_code=404, detail='任务不存在')
    return {
        'job_id': task.id,
        'project_id': task.project_id,
        'task_type': task.task_type,
        'status': task.status,
        'progress': task.progress,
        'result': task.result or {},
        'error': task.error or '',
        'created_at': task.created_at.isoformat() if task.created_at else '',
        'updated_at': task.updated_at.isoformat() if task.updated_at else '',
    }


# =============================================================================
# GET /jobs/{job_id}/events — SSE 进度订阅
# =============================================================================

@router.get('/jobs/{job_id}/events')
async def visguard_job_events(
    job_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """SSE 订阅任务进度。

    事件流：pending → progress(running) → completed | failed（终态后连接自动关闭）。
    轮询间隔 1s（DB 落盘为准，与 /ws/tasks/{job_id} 广播互为冗余通道）。
    """
    task = await _get_owned_task(job_id, db, user_id)
    if task is None:
        raise HTTPException(status_code=404, detail='任务不存在')

    from app.models.task import AsyncTask

    async def _event_stream():
        while True:
            res = await db.execute(
                select(AsyncTask).where(AsyncTask.id == job_id)
            )
            t = res.scalar_one_or_none()
            if t is None:
                yield 'event: error\ndata: {"detail":"任务不存在"}\n\n'
                return
            if t.status == 'completed':
                payload = {'job_id': job_id, 'status': 'completed', 'result': t.result or {}}
                yield f'event: completed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
                return
            if t.status == 'failed':
                payload = {
                    'job_id': job_id, 'status': 'failed', 'error': t.error or '',
                }
                yield f'event: failed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
                return
            # pending / running → 推送进度后继续轮询
            payload = {'job_id': job_id, 'status': t.status, 'progress': t.progress}
            yield f'event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
            await asyncio.sleep(1)

    return StreamingResponse(
        _event_stream(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# =============================================================================
# POST /jobs/{job_id}/cancel — 取消任务
# =============================================================================

@router.post('/jobs/{job_id}/cancel')
async def cancel_visguard_job(
    job_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """取消任务：DB 标记 failed + 尽力取消 asyncio 层任务。"""
    task = await _get_owned_task(job_id, db, user_id)
    if task is None:
        raise HTTPException(status_code=404, detail='任务不存在')
    if task.status in ('completed', 'failed'):
        raise HTTPException(status_code=409, detail='任务已结束')

    task.status = 'failed'
    task.error = '用户取消'
    await db.commit()

    running = get_running_task(job_id)
    if running is not None:
        running.cancel()
        logger.info('[VisGuard][Job] 已取消运行中任务: %s', job_id)
    return {'job_id': job_id, 'status': 'failed', 'message': '任务已取消'}