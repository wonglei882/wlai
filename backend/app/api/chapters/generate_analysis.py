"""章节背景分析（独立部署最小实现）。

主系统在章节生成后调用 AI 分析章节结构并写入 PlotAnalysis；
独立部署下做轻量本地分析（字数/标题/摘要 + 基础 PlotAnalysis 记录），
保证事件总线中的异步分析链路完整可用。
"""
import logging

logger = logging.getLogger(__name__)


async def analyze_chapter_background(chapter_id: str, user_id: str, project_id: str, task_id: str) -> None:
    """对章节执行背景分析（独立部署：本地统计 + 幂等写入 PlotAnalysis）。"""
    session = None
    try:
        from sqlalchemy import select

        from app.database import get_db_session
        from app.models.analysis_task import AnalysisTask
        from app.models.chapter import Chapter
        from app.models.memory import PlotAnalysis

        session = await get_db_session(user_id)

        result = await session.execute(select(AnalysisTask).where(AnalysisTask.id == task_id))
        task = result.scalar_one_or_none()
        if task:
            task.status = 'running'
            task.progress = 30
            await session.commit()

        result = await session.execute(select(Chapter).where(Chapter.id == chapter_id))
        chapter = result.scalar_one_or_none()
        if chapter is None:
            raise ValueError(f'章节不存在: {chapter_id}')

        content = chapter.content or ''
        word_count = chapter.word_count if chapter.word_count else len(content)

        # 幂等：同一章节已有分析记录则跳过写入
        result = await session.execute(select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter_id))
        if result.scalar_one_or_none() is None:
            session.add(
                PlotAnalysis(
                    project_id=project_id,
                    chapter_id=chapter_id,
                    plot_stage='过渡' if word_count < 1500 else '发展',
                    conflict_level=5,
                    emotional_tone='平静',
                    emotional_intensity=0.5,
                    hooks_count=0,
                    foreshadows_planted=0,
                    foreshadows_resolved=0,
                )
            )

        if task:
            task.status = 'success'
            task.progress = 100
        await session.commit()
        logger.info(
            '[generate_analysis] 章节分析完成: chapter=%s words=%s', chapter_id[:8], word_count
        )
    except Exception as e:  # noqa: BLE001 - 后台分析失败不阻断主流程
        logger.warning('[generate_analysis] 章节分析失败: %s', e)
        try:
            if session:
                from sqlalchemy import select

                from app.models.analysis_task import AnalysisTask

                result = await session.execute(select(AnalysisTask).where(AnalysisTask.id == task_id))
                task = result.scalar_one_or_none()
                if task:
                    task.status = 'failed'
                    task.progress = 100
                    task.error = str(e)[:500]
                    await session.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        if session:
            try:
                await session.close()
            except Exception:  # noqa: BLE001
                pass
