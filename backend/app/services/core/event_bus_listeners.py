"""PM 默认事件监听器——注册到事件总线，实现主动检查。

每个监听器职责：
- chapter.created  → 伏笔链扫描 + 因果图初始化
- chapter.updated  → 因果波及 + 一致性检查
- chapter.generating → 预生成质量预报
- chapter.generated → 自动写操作分析
- pm_tool.failed  → 自调参记录（连续失败 → 风险升级）

日志规范：
- routine 事件处理错误 → logger.info（主事件已成功，非阻塞）
- 真实数据问题（冲突/违反）→ logger.warning（需关注）
- 异常需堆栈调试 → logger.exception（结构化上报）
"""

import logging
import asyncio
from app.services.core.event_bus import event_bus
from app.services.core.event_bus import (
    EVENT_CHAPTER_CREATED,
    EVENT_CHAPTER_UPDATED,
    EVENT_CHAPTER_DELETED,
    EVENT_CHAPTER_GENERATING,
    EVENT_CHAPTER_GENERATED,
    EVENT_PM_TOOL_FAILED,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)


# ============================================================================
# 监听器实现
# ============================================================================


async def _on_chapter_created(db, chapter_id, project_id, user_id, **kwargs):
    """章节创建后：因果图推理 + 伏笔链扫描 + Skill 自动生长。"""
    own_db = None
    try:
        from app.database import get_db_session

        own_db = await get_db_session(user_id)
        from app.services.guardian import causal_graph
        from app.models.chapter import Chapter
        from app.api.settings import get_user_ai_service_from_db_by_usage

        r = await own_db.execute(select(Chapter).where(Chapter.id == chapter_id))
        ch = r.scalar_one_or_none()
        if ch and ch.content and len(ch.content) > 200:
            ai_svc = await get_user_ai_service_from_db_by_usage(user_id, own_db, 'default')
            n = await causal_graph.infer_from_content(own_db, chapter_id, project_id, ch.content[:5000], ai_service=ai_svc)
            logger.info(f'[EventBus] chapter.created: causal graph inferred {n} links')

        # Skill 自动生长：章节生成成功视为工具执行成功
        try:
            from app.services.inspiration_skills import auto_skill_from_tool_result

            content_len = len(ch.content or '')
            chapter_num = ch.chapter_number or 0
            await auto_skill_from_tool_result(
                user_id=user_id,
                user_input=f'第{chapter_num}章生成',
                tool_name='chapter_generation',
                tool_params={'chapter_id': chapter_id, 'project_id': project_id, 'chapter_number': chapter_num},
                tool_result={'success': True, 'message': f'第{chapter_num}章已生成 ({content_len}字)', 'data': {'word_count': content_len}},
            )
        except Exception as skill_err:
            logger.info(f'[EventBus] auto_skill_from_tool_result failed (非阻塞): {skill_err}')

        logger.debug(f'[EventBus] chapter.created: {chapter_id[:8]} in {project_id[:8]}')
    except Exception as e:
        logger.info(f'[EventBus] _on_chapter_created failed (非阻塞): {e}')
    finally:
        if own_db:
            try:
                await own_db.close()
            except Exception as e:
                logger.warning(f'[EventBus] db.close 失败: {e}')  # 资源清理失败不扩散


async def _on_chapter_updated(db, chapter_id, project_id, user_id, changed_fields=None, **kwargs):
    """章节修改后：因果波及检查 + 一致性。"""
    own_db = None
    try:
        from app.database import get_db_session

        own_db = await get_db_session(user_id)
        from app.services.guardian import causal_graph
        from app.api.settings import get_user_ai_service_from_db_by_usage
        from app.models.chapter import Chapter

        # 内容变化时重新推理因果
        if changed_fields and any(f in changed_fields for f in ('content', 'title', 'outline', 'expansion_plan')):
            r = await own_db.execute(select(Chapter).where(Chapter.id == chapter_id))
            ch = r.scalar_one_or_none()
            if ch and ch.content and len(ch.content) > 200:
                ai_svc = await get_user_ai_service_from_db_by_usage(user_id, own_db, 'default')
                n = await causal_graph.infer_from_content(own_db, chapter_id, project_id, ch.content[:5000], ai_service=ai_svc)
                logger.info(f'[EventBus] chapter.updated: reinferred {n} causal links')

        # 获取因果波及警告（日志记录）
        warning = await causal_graph.get_impact_warning(own_db, chapter_id, project_id)
        if warning:
            logger.info(f'[EventBus] chapter.updated impact:\n{warning[:200]}')

        if changed_fields:
            logger.debug(f'[EventBus] chapter.updated: {chapter_id[:8]} changed={changed_fields}')
    except Exception as e:
        logger.info(f'[EventBus] _on_chapter_updated failed (非阻塞): {e}')
    finally:
        if own_db:
            try:
                await own_db.close()
            except Exception as e:
                logger.warning(f'[EventBus] db.close 失败: {e}')  # 资源清理失败不扩散


async def _on_chapter_deleted(db, chapter_id, project_id, user_id, **kwargs):
    """章节删除后：因果图清理 + 支线完整性。"""
    own_db = None
    try:
        from app.database import get_db_session

        own_db = await get_db_session(user_id)
        from app.services.guardian import causal_graph

        n = await causal_graph.delete_for_chapter(own_db, chapter_id, project_id)
        logger.info(f'[EventBus] chapter.deleted: cleaned {n} causal links')
    except Exception as e:
        logger.info(f'[EventBus] _on_chapter_deleted failed (非阻塞): {e}')
    finally:
        if own_db:
            try:
                await own_db.close()
            except Exception as e:
                logger.warning(f'[EventBus] db.close 失败: {e}')  # 资源清理失败不扩散


async def _on_chapter_generating(db, chapter_id, project_id, user_id, **kwargs):
    """章节生成前：预生成质量预报。"""
    own_db = None
    try:
        from app.database import get_db_session

        own_db = await get_db_session(user_id)
        from app.services.quality_forecast import generate_forecast, get_risk_summary

        risks = await generate_forecast(own_db, project_id, chapter_id)
        if risks:
            summary = get_risk_summary(risks)
            logger.info(f'[EventBus] chapter.generating: {len(risks)} risks found\n{summary[:300]}')

            # 写入 pm_session_state 供 system_prompt 注入
            try:
                from app.models.pm_session_state import PMSessionState
                from sqlalchemy import desc, select, and_

                # 查找当前 session
                r = await own_db.execute(
                    select(PMSessionState)
                    .where(and_(PMSessionState.project_id == project_id, PMSessionState.user_id == user_id))
                    .order_by(desc(PMSessionState.created_at))
                    .limit(1)
                )
                state = r.scalar_one_or_none()
                if state:

                    def _serialize(rr):
                        return {
                            'severity': rr.severity,
                            'category': rr.category,
                            'chapter_number': rr.chapter_number,
                            'description': rr.description,
                            'suggestion': rr.suggestion,
                        }

                    state.extra_data = {
                        **(state.extra_data or {}),
                        'quality_forecast': [_serialize(r) for r in risks],
                    }
                    await own_db.commit()
            except Exception as e2:
                logger.info(f'[EventBus] forecast保存失败 (非阻塞): {e2}')
        else:
            logger.debug('[EventBus] chapter.generating: no risks')
    except Exception as e:
        logger.info(f'[EventBus] _on_chapter_generating failed (非阻塞): {e}')


async def _on_chapter_generated(db, chapter_id: str, project_id: str, user_id: str, **kwargs):
    """章节生成完成后自动分析（写入 PlotAnalysis）。

    因果图推理已移至 _on_chapter_created（章节创建时触发），
    避免与 _on_chapter_created + _on_chapter_generated 双触发导致重复 LLM 调用。
    """
    try:
        # 自动触发章节分析（写入 PlotAnalysis，供 load_context 读取）
        await _auto_run_analysis(db, chapter_id, project_id, user_id)
    except Exception as e:
        logger.info(f'[EventBus] _on_chapter_generated failed (非阻塞): {e}')


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
        asyncio.create_task(
            _delayed_consistency_check(
                chapter_id=chapter_id,
                project_id=project_id,
                user_id=user_id,
                delay=90,  # 分析通常 30-60s，留足余量
            )
        )
        logger.info(f'[EventBus] auto consistency check scheduled: chapter {chapter_id[:8]}')


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


# ===== 关系网自动更新 =====

# 正面互动词（增加亲密度）
_POSITIVE_INTERACTION = [
    '拥抱',
    '握手',
    '微笑',
    '感谢',
    '道歉',
    '承诺',
    '保护',
    '帮助',
    '安慰',
    '鼓励',
    '支持',
    '信任',
    '欣赏',
    '称赞',
    '敬佩',
    '感激',
    '和解',
    '原谅',
    '合作',
    '并肩',
    '携手',
    '救下',
    '救活',
    '治愈',
]
# 负面互动词（降低亲密度）
_NEGATIVE_INTERACTION = [
    '争吵',
    '打架',
    '威胁',
    '欺骗',
    '背叛',
    '背叛',
    '出卖',
    '嘲笑',
    '讽刺',
    '羞辱',
    '伤害',
    '攻击',
    '指责',
    '质问',
    '怒视',
    '冷笑',
    '无视',
    '拒绝',
    '驱赶',
    '抛弃',
    '暗杀',
    '陷害',
    '诬陷',
    '陷害',
]
# 中性互动词（建立关系）
_NEUTRAL_INTERACTION = [
    '相遇',
    '结识',
    '初见',
    '交谈',
    '对话',
    '认识',
    '重逢',
    '擦肩',
    '偶遇',
    '介绍',
    '请教',
    '询问',
    '回答',
    '告知',
    '打听',
]


async def _auto_update_relationships(db, chapter_id: str, project_id: str, user_id: str):
    """生成后自动更新关系网：提取角色互动并更新 CharacterRelationship 表。

    优化：使用句子分割 + jieba分词，只检测两角色在同一句子中的互动。
    """
    own_db = None
    try:
        from app.database import get_db_session

        own_db = await get_db_session(user_id)
        from app.models.chapter import Chapter
        from app.models.character import Character
        from app.models.relationship import CharacterRelationship
        from sqlalchemy import select
        import re

        # 获取章节内容
        r = await own_db.execute(select(Chapter).where(Chapter.id == chapter_id))
        chapter = r.scalar_one_or_none()
        if not chapter or not chapter.content:
            return
        content = chapter.content[:50000]
        current_chapter = chapter.chapter_number or 0

        # 获取项目所有角色
        chars_r = await own_db.execute(select(Character).where(Character.project_id == project_id).limit(50))
        chars = chars_r.scalars().all()
        if len(chars) < 2:
            return

        # 角色名 → character_id 映射（支持多字名优先匹配）
        char_map = {}
        for c in chars:
            if c.name:
                char_map[c.name.strip()] = c.id

        # 中文句子分割（按标点）
        sentences = re.split(r'[。！？；\n]+', content)

        updated_count = 0
        for sentence in sentences:
            if len(sentence) < 5:
                continue

            # 找出当前句子中的角色
            chars_in_sentence = []
            for name, cid in char_map.items():
                if name in sentence:
                    chars_in_sentence.append((name, cid))

            if len(chars_in_sentence) < 2:
                continue

            # 检测句子中的互动词
            found_positive = any(w in sentence for w in _POSITIVE_INTERACTION)
            found_negative = any(w in sentence for w in _NEGATIVE_INTERACTION)

            if not found_positive and not found_negative:
                continue

            # 计算亲密度变化
            intimacy_delta = 0
            if found_positive and not found_negative:
                intimacy_delta = +5
            elif found_negative and not found_positive:
                intimacy_delta = -5
            elif found_positive and found_negative:
                intimacy_delta = +2

            # 消除N+1：收集本句所有角色对，批量查询关系
            pair_ids = [(id1, id2) for i, (name1, id1) in enumerate(chars_in_sentence) for name2, id2 in chars_in_sentence[i + 1 :]]
            if not pair_ids:
                continue
            pair_ids_unique = list(set(pair_ids))
            all_from_ids = list(set(p[0] for p in pair_ids_unique))
            all_to_ids = list(set(p[1] for p in pair_ids_unique))
            # 批量查询所有 (from_id, to_id) 组合
            rels_result = await own_db.execute(
                select(CharacterRelationship).where(
                    CharacterRelationship.project_id == project_id,
                    CharacterRelationship.character_from_id.in_(all_from_ids),
                    CharacterRelationship.character_to_id.in_(all_to_ids),
                )
            )
            rels_map = {(r.character_from_id, r.character_to_id): r for r in rels_result.scalars().all()}

            # 为句子中的每对角色创建/更新关系
            for i, (name1, id1) in enumerate(chars_in_sentence):
                for name2, id2 in chars_in_sentence[i + 1 :]:
                    # 消除N+1：从预查字典查找关系记录
                    existing = rels_map.get((id1, id2))

                    if existing:
                        new_level = max(-100, min(100, (existing.intimacy_level or 50) + intimacy_delta))
                        existing.intimacy_level = new_level
                        existing.updated_at = __import__('datetime').datetime.now()
                        logger.info(f'🔗 [PM关系网] 更新: {name1}↔{name2} → {new_level} (第{current_chapter}章)')
                    else:
                        new_rel = CharacterRelationship(
                            id=str(__import__('uuid').uuid4()),
                            project_id=project_id,
                            character_from_id=id1,
                            character_to_id=id2,
                            intimacy_level=max(-100, min(100, 50 + intimacy_delta)),
                            status='active',
                            source='ai',
                        )
                        own_db.add(new_rel)
                        logger.info(f'🔗 [PM关系网] 新建: {name1}↔{name2} = {50 + intimacy_delta} (第{current_chapter}章)')

                    updated_count += 1

        if updated_count > 0:
            await own_db.commit()
            logger.info(f'✅ [PM关系网] 第{current_chapter}章更新 {updated_count} 条关系')

    except Exception as e:
        logger.info(f'[EventBus] _auto_update_relationships failed (非阻塞): {e}')
    finally:
        if own_db:
            try:
                await own_db.close()
            except Exception as e:
                logger.warning(f'[EventBus] db.close 失败: {e}')  # 资源清理失败不扩散


async def _on_pm_tool_failed(db, tool_name, error_type, error_message, project_id, user_id, **kwargs):
    """PM 工具失败后：记录到 MistakeLog + 触发自调参。"""
    own_db = None
    try:
        from app.database import get_db_session

        own_db = await get_db_session(user_id)
        from app.services.pm.self_tuning import record_failure

        await record_failure(own_db, tool_name, error_type or 'unknown', error_message, project_id, user_id)
        logger.info(f'[EventBus] pm_tool.failed recorded: {tool_name} ({error_type})')
    except Exception as e:
        logger.info(f'[EventBus] _on_pm_tool_failed failed (非阻塞): {e}')
    finally:
        if own_db:
            try:
                await own_db.close()
            except Exception as e:
                logger.warning(f'[EventBus] db.close 失败: {e}')  # 资源清理失败不扩散


# ============================================================================
# 注册函数（在 app 启动时调用一次）
# ============================================================================


def init_pm_event_listeners():
    """将 PM 默认监听器注册到事件总线。在 app lifespan startup 中调用。"""
    event_bus.register(EVENT_CHAPTER_CREATED, _on_chapter_created, 'pm_chapter_created')
    event_bus.register(EVENT_CHAPTER_UPDATED, _on_chapter_updated, 'pm_chapter_updated')
    event_bus.register(EVENT_CHAPTER_DELETED, _on_chapter_deleted, 'pm_chapter_deleted')
    event_bus.register(EVENT_CHAPTER_GENERATING, _on_chapter_generating, 'pm_chapter_generating')
    event_bus.register(EVENT_CHAPTER_GENERATED, _on_chapter_generated, 'pm_chapter_generated')
    event_bus.register(EVENT_PM_TOOL_FAILED, _on_pm_tool_failed, 'pm_tool_failed')
    logger.info('[EventBus] PM 事件监听器注册完成')
