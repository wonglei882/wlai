"""事件总线监听动作——章节生成后自动分析（写入 PlotAnalysis）。

从 event_bus_listeners.py 拆出（2026-08-25），职责单一：
- 幂等检查：已有 pending/running 分析任务则跳过
- 创建 AnalysisTask 并后台异步执行 analyze_chapter_background
- 分析完成后延迟触发一致性检查（_delayed_consistency_check）

日志规范与主文件一致：
- routine 处理错误 → logger.info（非阻塞）
- 真实数据问题 → logger.warning
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def _auto_run_analysis(db, chapter_id, project_id, user_id, **kwargs):
    """生成完成后自动分析章节（写入 PlotAnalysis）— 镜像 trigger_chapter_analysis。

    【幂等性】：如果该章节已有 pending/running 的分析任务，跳过。
    """
    own_db = None
    try:
        from app.database import get_db_session

        own_db = await get_db_session(user_id)
        from app.models.analysis_task import AnalysisTask
        from app.api.chapters.generate_analysis import analyze_chapter_background
        from sqlalchemy import select, and_

        # 【幂等性检查】：已有 pending/running 任务则跳过
        existing = await own_db.execute(
            select(AnalysisTask).where(
                and_(
                    AnalysisTask.chapter_id == chapter_id,
                    AnalysisTask.status.in_(['pending', 'running']),
                )
            )
        )
        existing_task = existing.scalar_one_or_none()
        if existing_task:
            logger.info(f'[EventBus] 跳过重复分析: chapter {chapter_id[:8]} 已有 {existing_task.status} 任务 {existing_task.id[:8]}')
            return

        # 1. 创建分析任务（自建独立 session）
        task = AnalysisTask(
            chapter_id=chapter_id,
            user_id=user_id,
            project_id=project_id,
            status='pending',
            progress=0,
        )
        own_db.add(task)
        await own_db.commit()
        await own_db.refresh(task)

        # 2. 短暂延迟确保写入完成（让分析会话可见）
        await asyncio.sleep(3)

        # 3. 后台分析（使用独立会话，不阻塞事件总线）
        asyncio.create_task(
            analyze_chapter_background(
                chapter_id=chapter_id,
                user_id=user_id,
                project_id=project_id,
                task_id=task.id,
            )
        )
        logger.info(f'[EventBus] auto plot analysis triggered: chapter {chapter_id[:8]}, task {task.id[:8]}')
    except Exception as e:
        logger.info(f'[EventBus] _auto_run_analysis failed (非阻塞): {e}')
    finally:
        if own_db:
            try:
                await own_db.close()
            except Exception as e:
                logger.warning(f'[EventBus] db.close 失败: {e}')  # 资源清理失败不扩散

        # 4. 延迟触发一致性检查（等分析完成并写入 PMConsistencyState 后再检查）
        from app.services.core.event_bus_listeners_consistency import _delayed_consistency_check

        asyncio.create_task(
            _delayed_consistency_check(
                chapter_id=chapter_id,
                project_id=project_id,
                user_id=user_id,
                delay=90,  # 分析通常 30-60s，留足余量
            )
        )
        logger.info(f'[EventBus] auto consistency check scheduled: chapter {chapter_id[:8]}')
