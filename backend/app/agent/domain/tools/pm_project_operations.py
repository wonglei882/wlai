"""PM 项目级写操作工具集 — 第2批（伏笔/金手指/分卷）"""

import contextlib
import json
import uuid
from sqlalchemy import select, update
from app.models.foreshadow import Foreshadow
from app.models.golden_finger import GoldenFinger
from app.models.outline import Outline
from app.logger import get_logger
from app.agent.core.command_registry import ToolDefinition, RiskLevel
from app.services.pm.pm_time import pm_now
from app.services.json_helper import safe_float, safe_int, safe_json_loads

logger = get_logger(__name__)


def _make_response(success: bool, message: str, data: dict | None = None) -> dict:
    r = {'success': success, 'message': message}
    if data:
        r.update(data)
    return r


# =============================================================================
# pm_create_foreshadow — 创建伏笔
# =============================================================================
async def pm_create_foreshadow(params: dict, db) -> dict:
    """创建新的伏笔（线索/悬念/反转）。

    参数：
        project_id: str       项目UUID（必填）
        title: str            伏笔标题（必填）
        content: str          伏笔详细内容（必填）
        category: str         分类（identity/神秘/mystery/item/relationship/event）
        plant_chapter_number: int  埋入章节号
        target_resolve_chapter_number: int  计划回收章节号
        importance: float     重要性 0.0-1.0
        strength: int         强度 1-10
        subtlety: int         隐藏度 1-10
        is_long_term: bool    是否长线伏笔
        related_characters: list  关联角色名列表
        tags: list            标签列表
        notes: str            创作备注

    示例：
        pm_create_foreshadow(project_id="xxx", title="耳机的嗡声", content="程野耳机里的嗡声来源成谜", category="mystery", plant_chapter_number=1, target_resolve_chapter_number=30)
    """  # noqa: E501  docstring示例行，不可改写内容
    project_id = params.get('project_id')
    title = params.get('title')
    content = params.get('content')

    if not project_id:
        return _make_response(False, '缺少 project_id')
    if not title:
        return _make_response(False, '缺少 title')
    if not content:
        return _make_response(False, '缺少 content')

    fs = Foreshadow(
        id=uuid.uuid4().hex,
        project_id=project_id,
        title=title,
        content=content,
        category=params.get('category', 'event'),
        plant_chapter_number=params.get('plant_chapter_number'),
        target_resolve_chapter_number=params.get('target_resolve_chapter_number'),
        importance=safe_float(params.get('importance', 0.5), 0.5),
        strength=safe_int(params.get('strength', 5), 5),
        subtlety=safe_int(params.get('subtlety', 5), 5),
        is_long_term=bool(params.get('is_long_term', False)),
        related_characters=json.dumps(params.get('related_characters', []), ensure_ascii=False),
        tags=json.dumps(params.get('tags', []), ensure_ascii=False),
        notes=params.get('notes', ''),
        status='active',
    )
    db.add(fs)
    await db.commit()

    logger.info(f'✅ PM创建伏笔: 「{title}」 project={project_id}')
    return _make_response(
        True,
        f'已创建伏笔「{title}」',
        {
            'foreshadow_id': fs.id,
            'title': title,
            'status': 'active',
        },
    )


# =============================================================================
# pm_update_foreshadow — 修改伏笔
# =============================================================================
async def pm_update_foreshadow(params: dict, db) -> dict:
    """修改已存在的伏笔。

    参数：
        foreshadow_id: str    伏笔UUID（必填）
        updates: dict         要更新的字段（支持：title/content/category/status/importance/strength/subtlety/target_resolve_chapter_number/related_characters/tags/notes）

    示例：
        pm_update_foreshadow(foreshadow_id="xxx", updates={"strength": 8, "notes": "需在第35章前回收"})
    """  # noqa: E501  docstring参数行，不可改写内容
    fs_id = params.get('foreshadow_id')
    updates = params.get('updates', {})

    if not fs_id:
        return _make_response(False, '缺少 foreshadow_id')
    if not updates:
        return _make_response(False, '缺少 updates')

    r = await db.execute(select(Foreshadow).where(Foreshadow.id == fs_id))
    fs = r.scalar_one_or_none()
    if not fs:
        return _make_response(False, f'未找到伏笔：{fs_id}')

    allowed = {
        'title',
        'content',
        'category',
        'status',
        'importance',
        'strength',
        'subtlety',
        'target_resolve_chapter_number',
        'related_characters',
        'tags',
        'notes',
        'is_long_term',
    }

    updated_fields = []
    for key, value in updates.items():
        if key in allowed and value is not None:
            if key == 'importance':
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    return _make_response(False, f'importance 必须为float：{value}')
            elif key == 'strength' or key == 'subtlety':
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    return _make_response(False, f'{key} 必须为整数：{value}')
            elif (key == 'related_characters' or key == 'tags') and isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            setattr(fs, key, value)
            updated_fields.append(key)

    if not updated_fields:
        return _make_response(False, '没有提供有效的更新字段')

    await db.commit()

    logger.info(f'✅ PM更新伏笔: 「{fs.title}」 字段={updated_fields}')
    return _make_response(
        True,
        f'已更新伏笔「{fs.title}」：{", ".join(updated_fields)}',
        {
            'foreshadow_id': fs.id,
            'updated_fields': updated_fields,
        },
    )


# =============================================================================
# pm_resolve_foreshadow — 回收伏笔
# =============================================================================
async def pm_resolve_foreshadow(params: dict, db) -> dict:
    """标记伏笔已回收（揭示）。

    参数：
        foreshadow_id: str    伏笔UUID（必填）
        resolution_text: str  回收时的揭示文本（原文摘录或概述）
        actual_resolve_chapter_number: int  实际回收章节号

    示例：
        pm_resolve_foreshadow(foreshadow_id="xxx", resolution_text="嗡声原来是...", actual_resolve_chapter_number=30)
    """
    fs_id = params.get('foreshadow_id')
    resolution_text = params.get('resolution_text', '')
    actual_ch = params.get('actual_resolve_chapter_number')

    if not fs_id:
        return _make_response(False, '缺少 foreshadow_id')

    r = await db.execute(select(Foreshadow).where(Foreshadow.id == fs_id))
    fs = r.scalar_one_or_none()
    if not fs:
        return _make_response(False, f'未找到伏笔：{fs_id}')

    fs.status = 'resolved'
    if resolution_text:
        fs.resolution_text = resolution_text
    if actual_ch is not None:
        with contextlib.suppress(TypeError, ValueError):
            fs.actual_resolve_chapter_number = int(actual_ch)

    await db.commit()

    logger.info(f'✅ PM回收伏笔: 「{fs.title}」 ch={actual_ch}')
    return _make_response(
        True,
        f'已回收伏笔「{fs.title}」',
        {
            'foreshadow_id': fs.id,
            'status': 'resolved',
            'actual_resolve_chapter_number': fs.actual_resolve_chapter_number,
        },
    )


# =============================================================================
# pm_update_golden_finger — 修改金手指
# =============================================================================
async def pm_update_golden_finger(params: dict, db) -> dict:
    """修改金手指（特殊能力/系统/道具）。

    参数：
        golden_finger_id: str    金手指UUID（与 name 二选一，优先）
        project_id: str          项目ID（配合 name 使用）
        name: str                金手指名称（用于查找）
        updates: dict            要更新的字段（支持：name/appearance/personality_consciousness/core_functions/energy_consumption/limitations_costs/background/traits）

    示例：
        pm_update_golden_finger(golden_finger_id="xxx", updates={"core_functions": "新增预知能力", "limitations_costs": "每次使用消耗24小时寿命"})
    """  # noqa: E501  docstring参数行，不可改写内容
    gf_id = params.get('golden_finger_id')
    project_id = params.get('project_id')
    name = params.get('name')
    updates = params.get('updates', {})

    if not updates:
        return _make_response(False, '缺少 updates')

    gf = None
    if gf_id:
        r = await db.execute(select(GoldenFinger).where(GoldenFinger.id == gf_id))
        gf = r.scalar_one_or_none()
    elif name and project_id:
        r = await db.execute(
            select(GoldenFinger).where(
                GoldenFinger.project_id == project_id,
                GoldenFinger.name == name,
            )
        )
        gf = r.scalar_one_or_none()
    else:
        return _make_response(False, '必须提供 golden_finger_id，或同时提供 name + project_id')

    if not gf:
        return _make_response(False, f'未找到金手指：{gf_id or f"name={name}"}')

    allowed = {
        'name',
        'appearance',
        'personality_consciousness',
        'core_functions',
        'energy_consumption',
        'limitations_costs',
        'background',
        'traits',
    }

    updated_fields = []
    for key, value in updates.items():
        if key in allowed and value is not None:
            setattr(gf, key, value)
            updated_fields.append(key)

    if not updated_fields:
        return _make_response(False, '没有提供有效的更新字段')

    await db.commit()

    logger.info(f'✅ PM更新金手指: 「{gf.name}」 字段={updated_fields}')
    return _make_response(
        True,
        f'已更新金手指「{gf.name}」：{", ".join(updated_fields)}',
        {
            'golden_finger_id': gf.id,
            'updated_fields': updated_fields,
        },
    )


# =============================================================================
# pm_update_volume — 修改分卷
# =============================================================================
async def pm_update_volume(params: dict, db) -> dict:
    """修改分卷信息（大纲结构中的卷）。

    参数：
        outline_id: str        大纲UUID（必填，卷存储在大纲的structure字段中）
        volume_order: int      卷序号，从1开始（必填）
        updates: dict          要更新的字段（支持：volume_title/volume_theme/volume_goal/volume_start_chapter/volume_end_chapter/volume_arc）

    示例：
        pm_update_volume(outline_id="xxx", volume_order=1, updates={"volume_title": "初入江湖", "volume_theme": "成长"})
    """
    outline_id = params.get('outline_id')
    volume_order = params.get('volume_order')
    updates = params.get('updates', {})

    if not outline_id:
        return _make_response(False, '缺少 outline_id')
    if volume_order is None:
        return _make_response(False, '缺少 volume_order')
    if not updates:
        return _make_response(False, '缺少 updates')

    try:
        vol_order = int(volume_order)
    except (TypeError, ValueError):
        return _make_response(False, f'volume_order 必须为整数：{volume_order}')

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
        if vol.get('volume_order') == vol_order:
            target_vol = vol
            break

    if not target_vol:
        return _make_response(False, f'未找到卷序号 {vol_order}（共{len(volumes)}卷）')

    allowed = {
        'volume_title',
        'volume_theme',
        'volume_goal',
        'volume_start_chapter',
        'volume_end_chapter',
        'volume_arc',
    }
    updated_fields = []
    for key, value in updates.items():
        if key in allowed and value is not None:
            if 'chapter' in key:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    return _make_response(False, f'{key} 必须为整数：{value}')
            target_vol[key] = value
            updated_fields.append(key)

    if not updated_fields:
        return _make_response(False, '没有提供有效的更新字段')

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

    logger.info(f'✅ PM更新分卷: 卷{vol_order} 字段={updated_fields}')
    return _make_response(
        True,
        f'已更新第{vol_order}卷：{", ".join(updated_fields)}',
        {
            'outline_id': outline_id,
            'volume_order': vol_order,
            'updated_fields': updated_fields,
        },
    )


# =============================================================================
# 注册
# =============================================================================
def register_pm_project_operations(registry) -> None:
    """注册 PM 项目级写操作工具（第2批：5个）。"""

    registry.register(
        ToolDefinition(
            name='pm_create_foreshadow',
            description='PM专用：在项目下创建新的伏笔（悬念/线索/反转）。',
            params_schema={
                'project_id': 'str: 项目UUID(必填)',
                'title': 'str: 伏笔标题(必填)',
                'content': 'str: 伏笔内容(必填)',
                'category': 'str: 分类(identity/mystery/item/relationship/event)',
                'plant_chapter_number': 'int: 埋入章节号',
            },
            required_params=['project_id', 'title', 'content'],
            param_types={
                'project_id': 'str',
                'title': 'str',
                'content': 'str',
                'category': 'str',
                'plant_chapter_number': 'int',
            },
            handler=handle_create_foreshadow,
            risk_level=RiskLevel.MEDIUM,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_update_foreshadow',
            description='PM专用：修改已存在的伏笔（内容/强度/回收计划等）。',
            params_schema={'foreshadow_id': 'str: 伏笔UUID(必填)', 'updates': 'dict: 要更新的字段'},
            required_params=['foreshadow_id'],
            param_types={'foreshadow_id': 'str'},
            handler=handle_update_foreshadow,
            risk_level=RiskLevel.MEDIUM,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_resolve_foreshadow',
            description='PM专用：标记伏笔已回收（揭示）。',
            params_schema={
                'foreshadow_id': 'str: 伏笔UUID(必填)',
                'resolution_text': 'str: 回收揭示文本',
                'actual_resolve_chapter_number': 'int: 实际回收章节号',
            },
            required_params=['foreshadow_id'],
            param_types={'foreshadow_id': 'str', 'resolution_text': 'str', 'actual_resolve_chapter_number': 'int'},
            handler=handle_resolve_foreshadow,
            risk_level=RiskLevel.MEDIUM,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_update_golden_finger',
            description='PM专用：修改金手指（特殊能力/系统/道具）。',
            params_schema={
                'golden_finger_id': 'str: 金手指UUID(优先)',
                'project_id': 'str: 项目ID',
                'name': 'str: 金手指名',
                'updates': 'dict: 要更新的字段',
            },
            required_params=['updates'],
            param_types={'golden_finger_id': 'str', 'project_id': 'str', 'name': 'str'},
            handler=handle_update_golden_finger,
            risk_level=RiskLevel.MEDIUM,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_update_volume',
            description='PM专用：修改分卷信息（大纲结构中的卷标题/主题/目标/章节范围）。',
            params_schema={
                'outline_id': 'str: 大纲UUID(必填)',
                'volume_order': 'int: 卷序号从1开始(必填)',
                'updates': 'dict: 要更新的字段',
            },
            required_params=['outline_id', 'volume_order'],
            param_types={'outline_id': 'str', 'volume_order': 'int'},
            handler=handle_update_volume,
            risk_level=RiskLevel.MEDIUM,
        )
    )


# -------------------------------------------------------------------
# handler 包装
# -------------------------------------------------------------------
async def handle_create_foreshadow(params: dict, db) -> dict:
    result = await pm_create_foreshadow(params, db)
    return [result.get('message', str(result))]


async def handle_update_foreshadow(params: dict, db) -> dict:
    result = await pm_update_foreshadow(params, db)
    return [result.get('message', str(result))]


async def handle_resolve_foreshadow(params: dict, db) -> dict:
    result = await pm_resolve_foreshadow(params, db)
    return [result.get('message', str(result))]


async def handle_update_golden_finger(params: dict, db) -> dict:
    result = await pm_update_golden_finger(params, db)
    return [result.get('message', str(result))]


async def handle_update_volume(params: dict, db) -> dict:
    result = await pm_update_volume(params, db)
    return [result.get('message', str(result))]
