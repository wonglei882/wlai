"""事件总线监听动作——伏笔状态自动回写与回收。

从 event_bus_listeners.py 拆出（2026-08-25），职责单一：
- _auto_update_foreshadow_status：检测章节内容是否埋入 pending 伏笔，自动标记 planted
- _auto_resolve_foreshadow：检测 planted 伏笔是否已解决，自动标记 resolved
- _RESOLVE_KEYWORDS：伏笔被回收时的解决信号词表

内部消费者：
- event_bus_listeners_consistency.py 的 _delayed_consistency_check 导入 _auto_update_foreshadow_status

日志规范与主文件一致：
- routine 处理错误 → logger.info（非阻塞）
- 真实数据问题 → logger.warning
"""

import logging

logger = logging.getLogger(__name__)


# ===== 伏笔 resolved 回收 =====

# 解决关键词（伏笔被回收时通常出现的词）
_RESOLVE_KEYWORDS = [
    '终于明白',
    '恍然大悟',
    '终于发现',
    '真相大白',
    '揭开真相',
    '化解了',
    '解决了',
    '击败了',
    '战胜了',
    '克服了困难',
    '解开了谜团',
    '水落石出',
    '尘埃落定',
    '圆满解决',
    '成功复仇',
    '报了大仇',
    '得到了答案',
    '揭开了谜底',
]


async def _auto_update_foreshadow_status(db, chapter_id: str, project_id: str, user_id: str):
    """生成后自动回写伏笔状态：检测章节内容是否埋入 pending 伏笔，自动标记 planted。"""
    try:
        from app.models.chapter import Chapter
        from app.models.foreshadow import Foreshadow
        from app.services.guardian.foreshadow_service import ForeshadowService
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        from app.database import get_engine

        # 使用独立会话
        engine = await get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionLocal() as fs_db:
            # 获取章节内容和章节号
            r = await fs_db.execute(select(Chapter).where(Chapter.id == chapter_id))
            chapter = r.scalar_one_or_none()
            if not chapter or not chapter.content:
                return
            content = chapter.content
            current_chapter = chapter.chapter_number or 0

            # 获取所有 pending 伏笔
            result = await fs_db.execute(
                select(Foreshadow).where(
                    Foreshadow.project_id == project_id,
                    Foreshadow.status == 'pending',
                )
            )
            pending_fs = result.scalars().all()
            if not pending_fs:
                logger.info(f'✅ [PM伏笔] 无 pending 伏笔 (第{current_chapter}章)')
                return

            # 检查每个伏笔的关键词是否出现在章节内容中
            service = ForeshadowService()
            planted_count = 0
            for fs in pending_fs:
                # 用 title + hint_text 作为匹配关键词（取前20字）
                keywords = [fs.title]
                if fs.hint_text:
                    keywords.append(fs.hint_text[:50])

                matched = False
                for kw in keywords:
                    if kw and len(kw) >= 2 and kw in content:
                        matched = True
                        break

                if matched:
                    # 自动标记 planted
                    from app.schemas.foreshadow import PlantForeshadowRequest

                    try:
                        await service.mark_as_planted(
                            fs_db,
                            fs.id,
                            PlantForeshadowRequest(
                                chapter_id=chapter_id,
                                chapter_number=current_chapter,
                                hint_text=content[:200],
                            ),
                        )
                        planted_count += 1
                        logger.info(f'📌 [PM伏笔] 自动标记 planted: {fs.title} (第{current_chapter}章)')
                    except Exception as mark_err:
                        logger.exception(f'⚠️ [PM伏笔] 标记失败: {fs.title} (已planted但标记失败): {mark_err}')

            if planted_count > 0:
                logger.info(f'✅ [PM伏笔] 自动标记 {planted_count} 个伏笔为 planted (第{current_chapter}章)')
            else:
                logger.info(f'✅ [PM伏笔] 检查完成，无新埋入 (第{current_chapter}章)')
    except Exception as e:
        logger.info(f'[EventBus] _auto_update_foreshadow_status failed (非阻塞): {e}')


async def _auto_resolve_foreshadow(db, chapter_id: str, project_id: str, user_id: str):
    """生成后自动检测伏笔是否已解决：检查 planted 伏笔在当前及后续章节是否被解决。"""
    own_db = None
    try:
        from app.database import get_db_session

        own_db = await get_db_session(user_id)
        from app.models.chapter import Chapter
        from app.models.foreshadow import Foreshadow
        from sqlalchemy import select

        # 获取章节号
        r = await own_db.execute(select(Chapter).where(Chapter.id == chapter_id))
        chapter = r.scalar_one_or_none()
        if not chapter:
            return
        current_chapter = chapter.chapter_number or 0
        content = (chapter.content or '')[:30000]

        # 获取所有 planted 伏笔
        planted_r = await own_db.execute(
            select(Foreshadow).where(
                Foreshadow.project_id == project_id,
                Foreshadow.status == 'planted',
            )
        )
        planted_list = planted_r.scalars().all()
        if not planted_list:
            return

        # 获取后续章节（扩大搜索范围）
        later_r = await own_db.execute(
            select(Chapter)
            .where(
                Chapter.project_id == project_id,
                Chapter.chapter_number >= current_chapter,
                Chapter.id != chapter_id,
                Chapter.content.isnot(None),
            )
            .order_by(Chapter.chapter_number)
            .limit(5)
        )
        later_content = '\n'.join((c.content or '')[:10000] for c in later_r.scalars().all())

        resolved_count = 0
        for fs in planted_list:
            # 检查伏笔标题/关键词是否在后续章节出现
            title = fs.title or ''
            hint = (fs.hint_text or '')[:50]

            # 条件：伏笔关键词出现 + 有解决关键词
            keyword_found = title in later_content or (hint and len(hint) >= 3 and hint in later_content)

            if not keyword_found:
                # 也在当前章节搜索
                keyword_found = title in content or (hint and len(hint) >= 3 and hint in content)

            if not keyword_found:
                continue

            # 伏笔关键词出现，检查是否有解决信号
            has_resolve_signal = any(kw in later_content or kw in content for kw in _RESOLVE_KEYWORDS)

            if has_resolve_signal:
                try:
                    fs.status = 'resolved'
                    fs.actual_resolve_chapter_number = current_chapter
                    fs.actual_resolve_chapter_id = chapter_id
                    fs.resolved_at = __import__('datetime').datetime.now()
                    resolved_count += 1
                    logger.info(f'✅ [PM伏笔] 自动标记 resolved: {fs.title} (第{current_chapter}章)')
                except Exception as e:
                    logger.warning(f'[event_bus_listeners] _auto_resolve_foreshadow 失败: {e}')

        if resolved_count > 0:
            await own_db.commit()
            logger.info(f'✅ [PM伏笔] 第{current_chapter}章回收 {resolved_count} 个伏笔为 resolved')
    except Exception as e:
        logger.info(f'[EventBus] _auto_resolve_foreshadow failed (非阻塞): {e}')
    finally:
        if own_db:
            try:
                await own_db.close()
            except Exception as e:
                logger.warning(f'[EventBus] db.close 失败: {e}')  # 资源清理失败不扩散
