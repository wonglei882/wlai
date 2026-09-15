"""后台任务运行器 — 在 asyncio 中执行生成任务并回写状态。

生成/巡检等长任务通过 submit_task 提交，任务行（pending -> running -> completed/failed）
在独立会话中更新，避免与请求会话耦合。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from app.database import _get_or_create_session_maker, get_engine
from app.models.task import AsyncTask

logger = logging.getLogger(__name__)

# task_id -> asyncio.Task（用于查询/取消）
_running: dict[str, asyncio.Task] = {}


async def _broadcast_progress(
    task_id: str, progress: float, status: str, result: dict | None = None,
) -> None:
    """向 /ws/tasks/{task_id} 频道的客户端推送进度（广播失败不影响任务执行）。"""
    try:
        from app.api.v1.ws import broadcast_task_progress

        await broadcast_task_progress(task_id, progress, status, result)
    except Exception as e:  # noqa: BLE001 - 广播是尽力而为的增强能力
        logger.debug('[TaskRunner] 进度广播失败 %s: %s', task_id, e)


async def _update_task(task_id: str, **fields) -> None:
    engine = await get_engine()
    SessionLocal = _get_or_create_session_maker(engine)
    async with SessionLocal() as session:
        result = await session.execute(select(AsyncTask).where(AsyncTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return
        for key, value in fields.items():
            setattr(task, key, value)
        await session.commit()


def submit_task(
    task: AsyncTask,
    worker: Callable[[], Awaitable[dict]],
) -> asyncio.Task:
    """提交一个后台任务。worker 返回结果 dict；异常时回写 error 并标记 failed。"""

    async def _runner() -> None:
        await _update_task(task.id, status='running', progress=0.05)
        await _broadcast_progress(task.id, 0.05, 'running')
        try:
            result = await worker()
            await _update_task(
                task.id, status='completed', progress=1.0, result=result,
            )
            await _broadcast_progress(task.id, 1.0, 'completed', result)
        except Exception as e:  # noqa: BLE001 - 任务异常必须兜底回写
            logger.exception('后台任务 %s 执行失败: %s', task.id, e)
            await _update_task(
                task.id, status='failed', progress=0.0,
                result={'error': str(e)}, error=str(e),
            )
            await _broadcast_progress(task.id, 0.0, 'failed', {'error': str(e)})

    loop = asyncio.get_running_loop()
    at = loop.create_task(_runner())
    _running[task.id] = at
    at.add_done_callback(lambda _t: _running.pop(task.id, None))
    return at


def get_running_task(task_id: str) -> asyncio.Task | None:
    """查询正在运行的后台任务。"""
    return _running.get(task_id)


def running_count() -> int:
    """当前运行中的后台任务数。"""
    return len(_running)
