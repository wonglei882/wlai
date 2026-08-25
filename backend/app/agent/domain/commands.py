"""基础只读工具注册（独立部署补齐）。

base 工具：read_project / read_chapter / list_chapters —— 供 PM Agent
在对话中快速读取项目状态，handler 直接查询数据库。
"""
import json
import logging

logger = logging.getLogger(__name__)


async def _read_project(params: dict, db) -> list[str]:
    from sqlalchemy import select

    from app.models.project import Project

    project_id = params.get('project_id') or ''
    if not project_id:
        return ['参数缺失: project_id']
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return [f'项目不存在: {project_id}']
    return [
        json.dumps(
            {
                'id': project.id,
                'title': project.title,
                'genre': project.genre,
                'status': project.status,
                'target_words': project.target_words,
                'current_words': project.current_words,
                'chapter_count': project.chapter_count,
            },
            ensure_ascii=False,
        )
    ]


async def _list_chapters(params: dict, db) -> list[str]:
    from sqlalchemy import select

    from app.models.chapter import Chapter

    project_id = params.get('project_id') or ''
    if not project_id:
        return ['参数缺失: project_id']
    result = await db.execute(
        select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number)
    )
    chapters = result.scalars().all()
    if not chapters:
        return ['该项目暂无章节']
    rows = []
    for ch in chapters:
        rows.append(
            {
                'id': ch.id,
                'chapter_number': ch.chapter_number,
                'title': ch.title,
                'word_count': ch.word_count,
                'status': ch.status,
            }
        )
    return [json.dumps(rows, ensure_ascii=False, default=str)]


async def _read_chapter(params: dict, db) -> list[str]:
    from sqlalchemy import select

    from app.models.chapter import Chapter

    chapter_id = params.get('chapter_id') or ''
    if not chapter_id:
        return ['参数缺失: chapter_id']
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        return [f'章节不存在: {chapter_id}']
    return [
        json.dumps(
            {
                'id': chapter.id,
                'chapter_number': chapter.chapter_number,
                'title': chapter.title,
                'summary': chapter.summary,
                'word_count': chapter.word_count,
                'status': chapter.status,
                'content': (chapter.content or '')[:2000],
            },
            ensure_ascii=False,
        )
    ]


def register_all_tools(registry) -> None:
    """注册 base 只读工具（read_project / list_chapters / read_chapter）。"""
    from app.agent.core.command_registry import RiskLevel, ToolDefinition

    registry.register(
        ToolDefinition(
            name='read_project',
            description='读取项目基本信息（标题/类型/状态/字数/章节数）',
            params_schema={'project_id': 'str: 项目UUID(必填)'},
            required_params=['project_id'],
            handler=_read_project,
            param_types={'project_id': 'str'},
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register(
        ToolDefinition(
            name='list_chapters',
            description='列出项目全部章节（章节号/标题/字数/状态）',
            params_schema={'project_id': 'str: 项目UUID(必填)'},
            required_params=['project_id'],
            handler=_list_chapters,
            param_types={'project_id': 'str'},
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register(
        ToolDefinition(
            name='read_chapter',
            description='读取章节详情（标题/摘要/正文前2000字/字数）',
            params_schema={'chapter_id': 'str: 章节UUID(必填)'},
            required_params=['chapter_id'],
            handler=_read_chapter,
            param_types={'chapter_id': 'str'},
            risk_level=RiskLevel.LOW,
        )
    )
