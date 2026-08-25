"""扩展工具注册（独立部署补齐）。

ext 工具在 base 工具之上提供分析/灵感能力：
- 复用项目内已有的 PM 工具注册（写操作/序列/项目/一致性/题材操作）
- 补充 analyze_chapter / foreshadow_scan / brainstorm_plot 三个分析类工具

工具间无同名冲突（base 工具为 read_/list_ 前缀，ext 为 pm_/analyze_/foreshadow_/brainstorm_ 前缀）。
"""
import logging

logger = logging.getLogger(__name__)


def register_all_tools(registry) -> None:
    """注册全部扩展工具。"""
    from app.agent.core.command_registry import RiskLevel, ToolDefinition
    from app.agent.domain.tools.pm_consistency import register_pm_consistency_tools
    from app.agent.domain.tools.pm_genre_ops import register_pm_genre_ops
    from app.agent.domain.tools.pm_project_operations import register_pm_project_operations
    from app.agent.domain.tools.pm_sequence import register_pm_sequence_tools
    from app.agent.domain.tools.pm_write_handlers import register_pm_write_operations

    # 复用项目内既有 PM 工具集
    register_pm_write_operations(registry)
    register_pm_sequence_tools(registry)
    register_pm_project_operations(registry)
    register_pm_consistency_tools(registry)
    register_pm_genre_ops(registry)

    # 补充分析/灵感工具
    registry.register(
        ToolDefinition(
            name='analyze_chapter',
            description='对章节做本地背景分析（结构/字数统计），返回分析摘要',
            params_schema={'chapter_id': 'str: 章节UUID(必填)'},
            required_params=['chapter_id'],
            handler=_analyze_chapter,
            param_types={'chapter_id': 'str'},
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register(
        ToolDefinition(
            name='foreshadow_scan',
            description='扫描章节中的伏笔线索（简单关键词匹配），返回伏笔清单',
            params_schema={'chapter_id': 'str: 章节UUID(必填)'},
            required_params=['chapter_id'],
            handler=_foreshadow_scan,
            param_types={'chapter_id': 'str'},
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register(
        ToolDefinition(
            name='brainstorm_plot',
            description='生成剧情灵感提示（独立部署为本地启发式建议）',
            params_schema={'theme': 'str: 创作主题(可选)'},
            required_params=[],
            handler=_brainstorm_plot,
            param_types={'theme': 'str'},
            risk_level=RiskLevel.LOW,
        )
    )


async def _analyze_chapter(params: dict, db) -> list[str]:
    import json

    from sqlalchemy import select

    from app.models.chapter import Chapter

    chapter_id = params.get('chapter_id') or ''
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        return [f'章节不存在: {chapter_id}']
    content = chapter.content or ''
    return [
        json.dumps(
            {
                'chapter_id': chapter.id,
                'chapter_number': chapter.chapter_number,
                'title': chapter.title,
                'word_count': len(content),
                'summary': (chapter.summary or '')[:200],
            },
            ensure_ascii=False,
        )
    ]


async def _foreshadow_scan(params: dict, db) -> list[str]:
    import json

    from sqlalchemy import select

    from app.models.chapter import Chapter

    chapter_id = params.get('chapter_id') or ''
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        return [f'章节不存在: {chapter_id}']
    content = chapter.content or ''
    hints = []
    for marker in ('他/她隐约觉得', '似乎暗示', '冥冥之中', '一个念头闪过', '仿佛在预示'):
        if marker in content:
            hints.append(marker)
    return [json.dumps({'chapter_id': chapter.id, 'found_hints': hints}, ensure_ascii=False)]


async def _brainstorm_plot(params: dict, db) -> list[str]:
    theme = params.get('theme') or '剧情推进'
    ideas = [
        f'围绕「{theme}」设计一次意料之外的转折，并让读者能回找到铺垫。',
        '引入一个新的次要角色，从侧面揭示主线矛盾。',
        '让一个早期伏笔在本段回收，同时埋下新的伏笔。',
    ]
    return ideas
