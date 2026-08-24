"""PM 流派/世界观/支线操作工具集 — 第3批"""

import json
from sqlalchemy import select, update
from app.models.project import Project
from app.models.outline import Outline
from app.models.chapter import Chapter
from app.logger import get_logger
from app.agent.core.command_registry import ToolDefinition, RiskLevel
from app.services.pm.pm_time import pm_now
from app.services.json_helper import safe_json_loads

logger = get_logger(__name__)


def _make_response(success: bool, message: str, data: dict | None = None) -> dict:
    r = {'success': success, 'message': message}
    if data:
        r.update(data)
    return r


# =============================================================================
# pm_update_world_setting — 修改世界设定
# =============================================================================
async def pm_update_world_setting(params: dict, db) -> dict:
    """修改项目世界设定（时间/地点/氛围/规则）。

    参数：
        project_id: str   项目UUID（必填）
        updates: dict     要更新的字段，支持：
            world_time_period: str   时间背景
            world_location: str      地理位置
            world_atmosphere: str    氛围基调
            world_rules: str         世界规则
            description: str         项目简介
            theme: str              主题
            genre: str              小说类型

    示例：
        pm_update_world_setting(project_id="xxx", updates={"world_atmosphere": "诡异惊悚", "world_rules": "订单不可取消"})
    """
    project_id = params.get('project_id')
    updates = params.get('updates', {})

    if not project_id:
        return _make_response(False, '缺少 project_id')
    if not updates:
        return _make_response(False, '缺少 updates')

    r = await db.execute(select(Project).where(Project.id == project_id))
    project = r.scalar_one_or_none()
    if not project:
        return _make_response(False, f'未找到项目：{project_id}')

    allowed = {
        'world_time_period',
        'world_location',
        'world_atmosphere',
        'world_rules',
        'description',
        'theme',
        'genre',
    }

    updated_fields = []
    values = {}
    for key, value in updates.items():
        if key in allowed and value is not None:
            values[key] = value
            updated_fields.append(key)

    if not updated_fields:
        return _make_response(False, '没有提供有效的更新字段')

    values['updated_at'] = pm_now()
    stmt = update(Project).where(Project.id == project_id).values(**values)
    await db.execute(stmt)
    await db.commit()

    logger.info(f'✅ PM更新世界设定: project={project.title} 字段={updated_fields}')
    return _make_response(
        True,
        f'已更新世界设定：{", ".join(updated_fields)}',
        {
            'project_id': project_id,
            'updated_fields': updated_fields,
        },
    )


# =============================================================================
# pm_create_subplot — 创建支线
# =============================================================================
async def pm_create_subplot(params: dict, db) -> dict:
    """在大纲中创建支线（归入某个卷）。

    支线存储在 Outline.structure.volumes[].subplots[] 中。

    参数：
        outline_id: str      大纲UUID（必填）
        volume_order: int     卷序号（必填，1起）
        title: str            支线标题（必填）
        summary: str          支线简介
        start_chapter: int    起始章节号
        end_chapter: int      预计收束章节号
        purpose: str           支线作用（丰富角色/推进主线/制造悬念）

    示例：
        pm_create_subplot(outline_id="xxx", volume_order=1, title="程野的身世之谜", summary="程野发现自己并非普通人", start_chapter=1, end_chapter=30)
    """
    outline_id = params.get('outline_id')
    volume_order = params.get('volume_order')
    title = params.get('title')
    summary = params.get('summary', '')
    start_chapter = params.get('start_chapter')
    end_chapter = params.get('end_chapter')
    purpose = params.get('purpose', '')

    if not outline_id:
        return _make_response(False, '缺少 outline_id')
    if volume_order is None:
        return _make_response(False, '缺少 volume_order')
    if not title:
        return _make_response(False, '缺少 title')

    r = await db.execute(select(Outline).where(Outline.id == outline_id))
    outline = r.scalar_one_or_none()
    if not outline:
        return _make_response(False, f'未找到大纲：{outline_id}')

    try:
        structure = safe_json_loads(outline.structure, {})
    except Exception:
        structure = {}

    volumes = structure.get('volumes', [])
    target_vol = None
    for vol in volumes:
        if vol.get('volume_order') == int(volume_order):
            target_vol = vol
            break

    if not target_vol:
        return _make_response(False, f'未找到卷序号 {volume_order}（共{len(volumes)}卷）')

    subplots = target_vol.get('subplots', [])
    new_subplot = {
        'id': f'subplot_{len(subplots) + 1}_{int(pm_now().timestamp())}',
        'title': title,
        'summary': summary,
        'start_chapter': start_chapter,
        'end_chapter': end_chapter,
        'purpose': purpose,
        'status': 'active',
    }
    subplots.append(new_subplot)
    target_vol['subplots'] = subplots
    structure['volumes'] = volumes

    stmt = (
        update(Outline)
        .where(Outline.id == outline_id)
        .values(
            structure=json.dumps(structure, ensure_ascii=False),
            updated_at=pm_now(),
        )
    )
    await db.execute(stmt)
    await db.commit()

    logger.info(f'✅ PM创建支线: 「{title}」 volume={volume_order}')
    return _make_response(
        True,
        f'已在第{volume_order}卷创建支线「{title}」',
        {
            'outline_id': outline_id,
            'subplot_id': new_subplot['id'],
            'title': title,
            'status': 'active',
        },
    )


# =============================================================================
# pm_add_conflict — 添加冲突
# =============================================================================
async def pm_add_conflict(params: dict, db) -> dict:
    """在大纲战略层添加冲突点。

    冲突存储在 Outline.structure.strategy.volumes[].conflicts[] 中。

    参数：
        outline_id: str       大纲UUID（必填）
        volume_order: int     卷序号（必填，1起）
        conflict_type: str    冲突类型（internal/external/social/nature）
        description: str      冲突描述（必填）
        involved_characters: list  涉及角色名列表
        escalation: str       升级方向
        resolution_approach: str   解决思路

    示例：
        pm_add_conflict(outline_id="xxx", volume_order=1, conflict_type="internal", description="程野内心挣扎：接单赚钱 vs 订单的诡异本质", involved_characters=["程野"])
    """  # noqa: E501  docstring示例行，不可改写内容
    outline_id = params.get('outline_id')
    volume_order = params.get('volume_order')
    description = params.get('description')
    conflict_type = params.get('conflict_type', 'external')
    involved_characters = params.get('involved_characters', [])
    escalation = params.get('escalation', '')
    resolution_approach = params.get('resolution_approach', '')

    if not outline_id:
        return _make_response(False, '缺少 outline_id')
    if volume_order is None:
        return _make_response(False, '缺少 volume_order')
    if not description:
        return _make_response(False, '缺少 description')

    r = await db.execute(select(Outline).where(Outline.id == outline_id))
    outline = r.scalar_one_or_none()
    if not outline:
        return _make_response(False, f'未找到大纲：{outline_id}')

    try:
        structure = safe_json_loads(outline.structure, {})
    except Exception:
        structure = {}

    strategy = structure.get('strategy', {})
    strategy_vols = strategy.get('volumes', [])

    target_vol = None
    for sv in strategy_vols:
        if sv.get('sort_order') == int(volume_order) or sv.get('volume_order') == int(volume_order):
            target_vol = sv
            break

    if not target_vol:
        # 卷不存在，创建之
        target_vol = {
            'sort_order': int(volume_order),
            'volume_order': int(volume_order),
            'title': f'第{volume_order}卷',
            'conflicts': [],
        }
        strategy_vols.append(target_vol)

    conflicts = target_vol.get('conflicts', [])
    new_conflict = {
        'id': f'conflict_{len(conflicts) + 1}_{int(pm_now().timestamp())}',
        'description': description,
        'type': conflict_type,
        'involved_characters': involved_characters,
        'escalation': escalation,
        'resolution_approach': resolution_approach,
        'status': 'active',
    }
    conflicts.append(new_conflict)
    target_vol['conflicts'] = conflicts
    strategy['volumes'] = strategy_vols
    structure['strategy'] = strategy

    stmt = (
        update(Outline)
        .where(Outline.id == outline_id)
        .values(
            structure=json.dumps(structure, ensure_ascii=False),
            updated_at=pm_now(),
        )
    )
    await db.execute(stmt)
    await db.commit()

    logger.info(f'✅ PM添加冲突: 「{description[:30]}」 volume={volume_order}')
    return _make_response(
        True,
        f'已在第{volume_order}卷添加冲突',
        {
            'outline_id': outline_id,
            'conflict_id': new_conflict['id'],
            'description': description[:50],
            'status': 'active',
        },
    )


# =============================================================================
# pm_update_arc — 更新情绪曲线
# =============================================================================
async def pm_update_arc(params: dict, db) -> dict:
    """更新章节的情绪曲线（写入 expansion_plan.emotional_arc）。

    参数：
        chapter_id: str       章节UUID（必填）
        emotion_arc: list    情绪曲线数据（必填），格式：
            [{"sequence": 0, "emotion": "极度绝望", "intensity": -4}, ...]
            emotion: 极度绝望/深重悲痛/高度紧张/焦虑低沉/轻微紧张/中性平静/
                     略带回暖/轻快希望/愉悦振奋/兴奋高燃/极度高燃
            intensity: -5 到 +5

    示例：
        pm_update_arc(chapter_id="xxx", emotion_arc=[{"sequence": 0, "emotion": "焦虑低沉", "intensity": -2}, {"sequence": 1, "emotion": "高度紧张", "intensity": -3}])
    """  # noqa: E501  docstring示例行，不可改写内容
    chapter_id = params.get('chapter_id')
    emotion_arc = params.get('emotion_arc')

    if not chapter_id:
        return _make_response(False, '缺少 chapter_id')
    if not emotion_arc:
        return _make_response(False, '缺少 emotion_arc')

    r = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = r.scalar_one_or_none()
    if not chapter:
        return _make_response(False, f'未找到章节：{chapter_id}')

    try:
        ep = safe_json_loads(chapter.expansion_plan, {})
    except Exception:
        ep = {}

    ep['emotional_arc'] = emotion_arc

    stmt = (
        update(Chapter)
        .where(Chapter.id == chapter_id)
        .values(
            expansion_plan=json.dumps(ep, ensure_ascii=False),
            updated_at=pm_now(),
        )
    )
    await db.execute(stmt)
    await db.commit()

    logger.info(f'✅ PM更新情绪曲线: ch={chapter.chapter_number} 共{len(emotion_arc)}个点')
    return _make_response(
        True,
        f'已更新情绪曲线（{len(emotion_arc)}个节点）',
        {
            'chapter_id': chapter_id,
            'chapter_number': chapter.chapter_number,
            'emotion_arc': emotion_arc,
        },
    )


# =============================================================================
# 注册
# =============================================================================
def register_pm_genre_ops(registry) -> None:
    """注册 PM 流派/世界观/支线操作工具（第3批：4个）。"""

    registry.register(
        ToolDefinition(
            name='pm_update_world_setting',
            description='PM专用：修改项目世界设定（时间背景/地理位置/氛围基调/世界规则）。',
            params_schema={'project_id': 'str: 项目UUID(必填)', 'updates': 'dict: 字段更新'},
            required_params=['project_id'],
            param_types={'project_id': 'str'},
            handler=handle_update_world_setting,
            risk_level=RiskLevel.MEDIUM,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_create_subplot',
            description='PM专用：在大纲卷中创建支线情节。',
            params_schema={
                'outline_id': 'str: 大纲UUID(必填)',
                'volume_order': 'int: 卷序号1起(必填)',
                'title': 'str: 支线标题(必填)',
                'summary': 'str: 支线简介',
                'start_chapter': 'int: 起始章节号',
                'end_chapter': 'int: 收束章节号',
                'purpose': 'str: 支线作用',
            },
            required_params=['outline_id', 'volume_order', 'title'],
            param_types={
                'outline_id': 'str',
                'volume_order': 'int',
                'title': 'str',
                'summary': 'str',
                'start_chapter': 'int',
                'end_chapter': 'int',
                'purpose': 'str',
            },
            handler=handle_create_subplot,
            risk_level=RiskLevel.MEDIUM,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_add_conflict',
            description='PM专用：在大纲战略层添加冲突点。',
            params_schema={
                'outline_id': 'str: 大纲UUID(必填)',
                'volume_order': 'int: 卷序号1起(必填)',
                'description': 'str: 冲突描述(必填)',
                'conflict_type': 'str: 冲突类型(internal/external/social)',
                'involved_characters': 'list: 涉及角色',
                'escalation': 'str: 升级方向',
                'resolution_approach': 'str: 解决思路',
            },
            required_params=['outline_id', 'volume_order', 'description'],
            param_types={
                'outline_id': 'str',
                'volume_order': 'int',
                'description': 'str',
                'conflict_type': 'str',
                'escalation': 'str',
                'resolution_approach': 'str',
            },
            handler=handle_add_conflict,
            risk_level=RiskLevel.MEDIUM,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_update_arc',
            description='PM专用：更新章节的情绪曲线（写入expansion_plan.emotional_arc）。',
            params_schema={'chapter_id': 'str: 章节UUID(必填)', 'emotion_arc': 'list: 情绪曲线数据(必填)'},
            required_params=['chapter_id', 'emotion_arc'],
            param_types={'chapter_id': 'str'},
            handler=handle_update_arc,
            risk_level=RiskLevel.MEDIUM,
        )
    )


# -------------------------------------------------------------------
# handler 包装
# -------------------------------------------------------------------
async def handle_update_world_setting(params: dict, db) -> dict:
    result = await pm_update_world_setting(params, db)
    return [result.get('message', str(result))]


async def handle_create_subplot(params: dict, db) -> dict:
    result = await pm_create_subplot(params, db)
    return [result.get('message', str(result))]


async def handle_add_conflict(params: dict, db) -> dict:
    result = await pm_add_conflict(params, db)
    return [result.get('message', str(result))]


async def handle_update_arc(params: dict, db) -> dict:
    result = await pm_update_arc(params, db)
    return [result.get('message', str(result))]
