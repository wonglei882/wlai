"""PM 写操作工具集 — Handler 包装层（第3批）

由 pm_write_operations.py 拆分而来（god file 专项重构）。
"""

from app.agent.core.command_registry import ToolDefinition, RiskLevel
from app.agent.domain.tools.pm_write_crud import (
    pm_update_outline,
    pm_update_body,
    pm_update_chapter_context,
    pm_update_character,
    pm_update_character_state,
    pm_delete_chapter,
    pm_delete_foreshadow,
    pm_delete_subplot,
)
from app.agent.domain.tools.pm_write_generate import (
    pm_generate_volume_outlines,
    pm_generate_pacing_suggestion,
    pm_suggest_conflict,
    pm_create_chapter_with_plan,
)

from app.agent.domain.tools.pm_write_diagnose import (
    pm_analyze_relationships,
    pm_diagnose_project,
)

# =============================================================================
# 注册入口
# =============================================================================


def register_pm_write_operations(registry):
    """注册第1批写操作工具（5个）"""
    registry.register(
        ToolDefinition(
            name='pm_update_outline',
            description='PM专用：修改章节的展开规划（章纲骨架），更新序列内容/字数/情绪值等',
            params_schema={
                'chapter_id': 'str: 章节UUID(必填)',
                'sequence_index': 'int: 序列序号(必填 0~7)',
                'core_task': 'str: 核心任务描述',
                'target_words': 'int: 目标字数',
                'emotion_value': 'int: 情绪值',
                'updates': 'dict: 其他字段字典',
            },
            required_params=['chapter_id', 'sequence_index'],
            param_types={'chapter_id': 'str'},
            handler=handle_update_outline,
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register(
        ToolDefinition(
            name='pm_update_body',
            description='PM专用：修改章节正文内容',
            params_schema={
                'chapter_id': 'str: 章节UUID(必填)',
                'content': 'str: 正文内容(必填)',
                'append': 'bool: 是否追加模式(默认覆盖)',
            },
            required_params=['chapter_id', 'content'],
            param_types={'chapter_id': 'str'},
            handler=handle_update_body,
            risk_level=RiskLevel.MEDIUM,
        )
    )
    registry.register(
        ToolDefinition(
            name='pm_update_chapter_context',
            description='PM专用：修改章节上下文（标题/摘要/世界观/基调）',
            params_schema={
                'chapter_id': 'str: 章节UUID(必填)',
                'title': 'str: 新标题',
                'chapter_summary': 'str: 本章摘要',
                'world_state': 'str: 本章世界观状态',
                'tone': 'str: 本章基调',
                'chapter_goal': 'str: 本章创作目标',
            },
            required_params=['chapter_id'],
            param_types={'chapter_id': 'str'},
            handler=handle_update_chapter_context,
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register(
        ToolDefinition(
            name='pm_update_character',
            description='PM专用：修改角色设定（名称/性别/性格/背景/目标/状态/关系）',
            params_schema={
                'project_id': 'str: 项目UUID(必填)',
                'character_id': 'str: 角色UUID(必填)',
                'name': 'str: 名称',
                'gender': 'str: 性别',
                'age': 'str: 年龄',
                'personality': 'str: 性格',
                'background': 'str: 背景故事',
                'goal': 'str: 角色目标',
                'status': 'str: 角色状态',
                'relationship': 'str: 关系描述',
            },
            required_params=['project_id', 'character_id'],
            param_types={'project_id': 'str'},
            handler=handle_update_character,
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register(
        ToolDefinition(
            name='pm_update_character_state',
            description='PM专用：更新角色当前状态（位置/情绪）',
            params_schema={
                'character_id': 'str: 角色UUID(必填)',
                'state': 'str: 状态描述(必填)',
            },
            required_params=['character_id', 'state'],
            param_types={'character_id': 'str'},
            handler=handle_update_character_state,
            risk_level=RiskLevel.LOW,
        )
    )


def _register_p2_tools(registry):
    """注册P2删类+生成类工具（7个）"""
    # 删类
    registry.register(
        ToolDefinition(
            name='pm_delete_chapter',
            description='PM专用：删除章节（软删除）',
            params_schema={'chapter_id': 'str: 章节UUID(必填)'},
            required_params=['chapter_id'],
            param_types={'chapter_id': 'str'},
            handler=handle_delete_chapter,
            risk_level=RiskLevel.MEDIUM,
        )
    )
    registry.register(
        ToolDefinition(
            name='pm_delete_foreshadow',
            description='PM专用：删除伏笔',
            params_schema={'foreshadow_id': 'str: 伏笔UUID(必填)'},
            required_params=['foreshadow_id'],
            param_types={'foreshadow_id': 'str'},
            handler=handle_delete_foreshadow,
            risk_level=RiskLevel.MEDIUM,
        )
    )
    registry.register(
        ToolDefinition(
            name='pm_delete_subplot',
            description='PM专用：删除支线',
            params_schema={
                'outline_id': 'str: 大纲UUID(必填)',
                'volume_order': 'int: 卷序号(必填)',
                'subplot_id': 'str: 支线ID(必填)',
            },
            required_params=['outline_id', 'volume_order', 'subplot_id'],
            param_types={'outline_id': 'str'},
            handler=handle_delete_subplot,
            risk_level=RiskLevel.MEDIUM,
        )
    )
    # 生成类
    registry.register(
        ToolDefinition(
            name='pm_generate_volume_outlines',
            description='PM专用：AI生成分卷大纲（写入Outline.structure.volumes）',
            params_schema={
                'outline_id': 'str: 大纲UUID(必填)',
                'volume_count': 'int: 卷数(默认3)',
            },
            required_params=['outline_id'],
            param_types={'outline_id': 'str'},
            handler=handle_generate_volume_outlines,
            risk_level=RiskLevel.MEDIUM,
        )
    )
    registry.register(
        ToolDefinition(
            name='pm_generate_pacing_suggestion',
            description='PM专用：AI为章节生成节奏建议',
            params_schema={'chapter_id': 'str: 章节UUID(必填)'},
            required_params=['chapter_id'],
            param_types={'chapter_id': 'str'},
            handler=handle_generate_pacing,
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register(
        ToolDefinition(
            name='pm_suggest_conflict',
            description='PM专用：AI推荐当前卷的核心冲突点',
            params_schema={
                'project_id': 'str: 项目UUID(必填)',
                'volume_order': 'int: 卷序号',
            },
            required_params=['project_id'],
            param_types={'project_id': 'str'},
            handler=handle_suggest_conflict,
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register(
        ToolDefinition(
            name='pm_create_chapter_with_plan',
            description='PM专用：创建章节并自动生成8序列规划',
            params_schema={
                'project_id': 'str: 项目UUID(必填)',
                'chapter_number': 'int: 章节号',
                'title': 'str: 章节标题',
            },
            required_params=['project_id'],
            param_types={'project_id': 'str'},
            handler=handle_create_chapter_with_plan,
            risk_level=RiskLevel.MEDIUM,
        )
    )

    # PM 小说管理增强：整合诊断
    registry.register(
        ToolDefinition(
            name='pm_diagnose_project',
            description='PM专用：整合所有已有分析服务，生成完整项目诊断报告（伏笔/角色/文风/趋势/POV/结构/关系）',
            params_schema={'project_id': 'str: 项目UUID(必填)'},
            required_params=['project_id'],
            param_types={'project_id': 'str'},
            handler=handle_diagnose_project,
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register(
        ToolDefinition(
            name='pm_analyze_relationships',
            description='PM专用：分析角色关系网，生成关系图谱摘要+断线预警+冲突建议',
            params_schema={'project_id': 'str: 项目UUID(必填)'},
            required_params=['project_id'],
            param_types={'project_id': 'str'},
            handler=handle_analyze_relationships,
            risk_level=RiskLevel.LOW,
        )
    )


# =============================================================================
# handler 包装（保持与 ToolRegistry 兼容的签名）
# =============================================================================


async def handle_update_outline(params: dict, db) -> list:
    r = await pm_update_outline(params, db)
    return [r.get('message', str(r))]


async def handle_update_body(params: dict, db) -> list:
    r = await pm_update_body(params, db)
    return [r.get('message', str(r))]


async def handle_update_chapter_context(params: dict, db) -> list:
    r = await pm_update_chapter_context(params, db)
    return [r.get('message', str(r))]


async def handle_update_character(params: dict, db) -> list:
    r = await pm_update_character(params, db)
    return [r.get('message', str(r))]


async def handle_update_character_state(params: dict, db) -> list:
    r = await pm_update_character_state(params, db)
    return [r.get('message', str(r))]


async def handle_delete_chapter(params: dict, db) -> list:
    r = await pm_delete_chapter(params, db)
    return [r.get('message', str(r))]


async def handle_delete_foreshadow(params: dict, db) -> list:
    r = await pm_delete_foreshadow(params, db)
    return [r.get('message', str(r))]


async def handle_delete_subplot(params: dict, db) -> list:
    r = await pm_delete_subplot(params, db)
    return [r.get('message', str(r))]


async def handle_generate_volume_outlines(params: dict, db) -> list:
    r = await pm_generate_volume_outlines(params, db)
    return [r.get('message', str(r))]


async def handle_generate_pacing(params: dict, db) -> list:
    r = await pm_generate_pacing_suggestion(params, db)
    return [r.get('message', str(r))]


async def handle_suggest_conflict(params: dict, db) -> list:
    r = await pm_suggest_conflict(params, db)
    return [r.get('message', str(r))]


async def handle_diagnose_project(params: dict, db) -> list:
    project_id = params.get('project_id', '')
    r = await pm_diagnose_project(project_id, db)
    return [r.get('message', str(r))]


async def handle_analyze_relationships(params: dict, db) -> list:
    project_id = params.get('project_id', '')
    r = await pm_analyze_relationships(project_id, db)
    return [r.get('message', str(r))]


async def handle_create_chapter_with_plan(params: dict, db) -> list:
    r = await pm_create_chapter_with_plan(params, db)
    return [r.get('message', str(r))]
