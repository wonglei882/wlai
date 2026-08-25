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

拆分说明（2026-08-25）：重量级监听动作按领域拆至：
- event_bus_listeners_analysis：章节生成后自动分析
- event_bus_listeners_consistency：一致性检查 + 延迟调度 + 即时巡检
- event_bus_listeners_foreshadow：伏笔状态自动回写/回收
- event_bus_listeners_relationships：关系网自动更新
本文件保留 6 个监听器薄壳 + 注册函数 + 兼容再导出（_auto_run_consistency_check 供
app/services/pm/pm_fix_executors.py 消费，_auto_run_analysis 供 _on_chapter_generated 调用）。
"""

import logging
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
# 监听器实现（薄壳，重活委托给拆分的领域模块）
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
        from app.services.core.event_bus_listeners_analysis import _auto_run_analysis

        # 自动触发章节分析（写入 PlotAnalysis，供 load_context 读取）
        await _auto_run_analysis(db, chapter_id, project_id, user_id)
    except Exception as e:
        logger.info(f'[EventBus] _on_chapter_generated failed (非阻塞): {e}')


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
# 兼容再导出（外部模块直接导入路径）
# ============================================================================
# - pm_fix_executors.py: from app.services.core.event_bus_listeners import _auto_run_consistency_check
from app.services.core.event_bus_listeners_consistency import _auto_run_consistency_check  # noqa: E402, F401


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
