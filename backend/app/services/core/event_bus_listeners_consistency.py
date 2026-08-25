"""事件总线监听动作——PM 一致性检查链路（角色状态 + 世界规则）。

从 event_bus_listeners.py 拆出（2026-08-25），职责单一：
- _auto_run_consistency_check：生成后自动一致性检查（角色状态 + 世界规则）
- _delayed_consistency_check：延迟调度一致性检查 + 伏笔状态回写
- _trigger_immediate_pm_scan：一致性检查完成后触发即时 PM 巡检（P0.3）

外部消费者：
- app/services/pm/pm_fix_executors.py 经 event_bus_listeners 再导入 _auto_run_consistency_check
- event_bus_listeners_analysis.py 导入 _delayed_consistency_check

日志规范与主文件一致：
- routine 处理错误 → logger.info（非阻塞）
- 真实数据问题（冲突/违反）→ logger.warning
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def _auto_run_consistency_check(db, chapter_id: str, project_id: str, user_id: str) -> dict:
    """生成后自动一致性检查：角色状态 + 世界规则。返回检测到的问题。"""
    result = {'character_conflicts': [], 'world_violations': []}
    try:
        from app.models.chapter import Chapter
        from sqlalchemy import select
        from app.agent.domain.tools.pm_consistency import (
            handle_pm_check_character_state,
            handle_pm_check_world_consistency,
        )
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        from app.database import get_engine

        # 使用独立会话（避免复用事件总线/批处理会话的并发问题）
        engine = await get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionLocal() as check_db:
            # 获取章节号
            r = await check_db.execute(select(Chapter).where(Chapter.id == chapter_id))
            chapter = r.scalar_one_or_none()
            if not chapter:
                return result
            current_chapter = chapter.chapter_number or 0

            # 1. 角色状态一致性检查
            char_result = await handle_pm_check_character_state(
                {
                    'project_id': project_id,
                    'current_chapter': current_chapter,
                },
                check_db,
            )
            if isinstance(char_result, list):
                conflicts = [x for x in char_result if '冲突' in str(x) or '跳变' in str(x)]
                if conflicts:
                    logger.warning(f'⚠️ [PM一致性] 角色状态冲突: {conflicts}')
                    result['character_conflicts'] = conflicts
            elif isinstance(char_result, dict):
                if char_result.get('conflicts'):
                    logger.warning(f'⚠️ [PM一致性] 角色状态冲突: {char_result.get("conflicts")}')
                    result['character_conflicts'] = char_result.get('conflicts', [])

            # 2. 世界规则一致性检查
            world_result = await handle_pm_check_world_consistency(
                {
                    'project_id': project_id,
                    'current_chapter': current_chapter,
                },
                check_db,
            )
            if isinstance(world_result, list):
                violations = [x for x in world_result if '违反' in str(x) or '冲突' in str(x)]
                if violations:
                    logger.warning(f'⚠️ [PM一致性] 世界规则违反: {violations}')
                    result['world_violations'] = violations
            elif isinstance(world_result, dict):
                if world_result.get('violations'):
                    logger.warning(f'⚠️ [PM一致性] 世界规则违反: {world_result.get("violations")}')
                    result['world_violations'] = world_result.get('violations', [])

            logger.info(f'✅ [PM一致性] 检查完成: 第{current_chapter}章')
    except Exception as e:
        logger.info(f'[EventBus] _auto_run_consistency_check failed (非阻塞): {e}')
    return result


async def _delayed_consistency_check(chapter_id: str, project_id: str, user_id: str, delay: int = 90):
    """延迟执行 PM 一致性检查（等分析完成并写入状态快照后）。"""
    await asyncio.sleep(delay)
    try:
        # 新建独立会话（不复用事件总线会话）
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        from app.database import get_engine

        engine = await get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionLocal() as db:
            await _auto_run_consistency_check(db, chapter_id, project_id, user_id)
            from app.services.core.event_bus_listeners_foreshadow import _auto_update_foreshadow_status

            await _auto_update_foreshadow_status(db, chapter_id, project_id, user_id)
    except Exception as e:
        logger.info(f'[EventBus] _delayed_consistency_check failed (非阻塞): {e}')

    # P0.3: 一致性检查完成后触发即时 PM 巡检（不等 30 分钟间隔）
    # 让质量评分、段落格式等新维度能立即检测新生成的章节
    try:
        asyncio.create_task(_trigger_immediate_pm_scan(project_id, user_id))
    except Exception as trigger_e:
        logger.debug(f'[EventBus] 即时巡检触发失败（非阻塞）: {trigger_e}')


async def _trigger_immediate_pm_scan(project_id: str, user_id: str):
    """章节生成 + 一致性检查完成后，触发即时 PM 巡检。

    与后台 30 分钟定时巡检互补：让质量评分/段落格式等维度能立即检测新章节。
    使用独立 session，不影响事件总线流程。
    """
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        from app.database import get_engine
        from app.services.pm.pm_agent import _scan_single_project

        engine = await get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionLocal() as db:
            result = await _scan_single_project(db, project_id, user_id)
            total = sum(len(v) for v in result.get('issues', {}).values())
            if total > 0:
                logger.info(f'[EventBus P0.3] 即时巡检完成: project={project_id[:8]} 发现 {total} 问题, 决策 {len(result.get("decisions", []))} 次')
            else:
                logger.debug(f'[EventBus P0.3] 即时巡检完成: project={project_id[:8]} 无问题')
    except Exception as e:
        logger.info(f'[EventBus P0.3] _trigger_immediate_pm_scan failed (非阻塞): {e}')
