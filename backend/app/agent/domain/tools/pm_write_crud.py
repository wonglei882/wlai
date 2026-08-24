"""PM 写操作工具集 — CRUD 操作（第1批+删类）

由 pm_write_operations.py 拆分而来（god file 专项重构）。
"""

from app.agent.domain.tools.pm_write_base import _make_response, safe_int, safe_json_loads

"""
PM 写操作工具集 — 第1批 + 第2批（P2:删类+生成类）
每个工具包含：参数校验、DB读写、一致性校验、日志记录
"""
import json
from sqlalchemy import select, update, delete
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.foreshadow import Foreshadow
from app.models.outline import Outline
from app.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# 第1批：写操作工具（5个）
# =============================================================================


async def pm_update_outline(params: dict, db) -> dict:
    """修改章节的展开规划（章纲骨架）。更新序列内容、字数、情绪值等。"""
    chapter_id = params.get('chapter_id', '')
    sequence_index = safe_int(params.get('sequence_index', -1), -1)
    updates = params.get('updates', {})
    core_task = params.get('core_task', '')
    target_words = params.get('target_words', 0)
    emotion_value = params.get('emotion_value', 0)

    if not chapter_id:
        return _make_response(False, '缺少 chapter_id')

    r = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = r.scalar_one_or_none()
    if not chapter:
        return _make_response(False, f'章节不存在: {chapter_id}')

    try:
        ep = safe_json_loads(chapter.expansion_plan, {})
    except Exception:
        ep = {}

    sequences = ep.get('sequences', [])
    if not sequences:
        return _make_response(False, '该章节尚无任何序列规划')

    if sequence_index < 0:
        return _make_response(False, f'必须指定 sequence_index（0~{len(sequences) - 1}）')

    if sequence_index >= len(sequences):
        return _make_response(False, f'sequence_index {sequence_index} 超出范围（共{len(sequences)}个）')

    seq = sequences[sequence_index]
    changed = []

    if updates and isinstance(updates, dict):
        for key, val in updates.items():
            old_val = seq.get(key, '')
            seq[key] = val
            if str(old_val)[:20] != str(val)[:20]:
                changed.append(key)
    if core_task:
        seq['core_task'] = core_task
        changed.append('core_task')
    if target_words:
        seq['target_words'] = target_words
        changed.append('target_words')
    if emotion_value:
        seq['emotion_value'] = emotion_value
        changed.append('emotion_value')

    sequences[sequence_index] = seq
    ep['sequences'] = sequences

    stmt = update(Chapter).where(Chapter.id == chapter_id).values(expansion_plan=json.dumps(ep, ensure_ascii=False))
    await db.execute(stmt)
    await db.commit()

    logger.info(f'PM更新outline: ch{getattr(chapter, "chapter_number", "?")} seq{sequence_index}')
    return _make_response(True, f'已更新序列「{seq.get("label", "")}」: {", ".join(changed)}', {'updated': changed, 'sequence': seq})


async def pm_update_body(params: dict, db) -> dict:
    """修改章节正文内容"""
    chapter_id = params.get('chapter_id', '')
    content = params.get('content', '')
    append = params.get('append', False)

    if not chapter_id:
        return _make_response(False, '缺少 chapter_id')

    r = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = r.scalar_one_or_none()
    if not chapter:
        return _make_response(False, f'章节不存在: {chapter_id}')

    new_content = (chapter.content or '') + content if append else content

    stmt = update(Chapter).where(Chapter.id == chapter_id).values(content=new_content)
    await db.execute(stmt)
    await db.commit()

    ch_num = getattr(chapter, 'chapter_number', '?')
    logger.info(f'PM更新正文: ch{ch_num} {len(content)}字')
    return _make_response(
        True,
        f'已更新第{ch_num}章正文（{"追加" if append else "覆盖"}）',
        {'chapters': {'chapter_number': ch_num, 'content_length': len(new_content)}},
    )


async def pm_update_chapter_context(params: dict, db) -> dict:
    """修改章节的上下文信息（标题/摘要/世界观/基调）"""
    chapter_id = params.get('chapter_id', '')
    title = params.get('title', '')
    chapter_summary = params.get('chapter_summary', '')
    world_state = params.get('world_state', '')
    tone = params.get('tone', '')
    chapter_goal = params.get('chapter_goal', '')

    if not chapter_id:
        return _make_response(False, '缺少 chapter_id')

    r = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = r.scalar_one_or_none()
    if not chapter:
        return _make_response(False, f'章节不存在: {chapter_id}')

    try:
        ep = safe_json_loads(chapter.expansion_plan, {})
    except Exception:
        ep = {}

    ctx = ep.get('chapter_context', {})
    changed = []
    if title:
        ctx['title'] = title
        changed.append('title')
    if chapter_summary:
        ctx['chapter_summary'] = chapter_summary
        changed.append('chapter_summary')
    if world_state:
        ctx['world_state'] = world_state
        changed.append('world_state')
    if tone:
        ctx['tone'] = tone
        changed.append('tone')
    if chapter_goal:
        ctx['chapter_goal'] = chapter_goal
        changed.append('chapter_goal')

    ep['chapter_context'] = ctx
    stmt = update(Chapter).where(Chapter.id == chapter_id).values(expansion_plan=json.dumps(ep, ensure_ascii=False))
    await db.execute(stmt)
    await db.commit()

    ch_num = getattr(chapter, 'chapter_number', '?')
    logger.info(f'PM更新上下文: ch{ch_num} {changed}')
    return _make_response(
        True, f'已更新第{ch_num}章上下文: {", ".join(changed)}', {'chapters': {'chapter_number': ch_num, 'updated_fields': changed}}
    )


async def pm_update_character(params: dict, db) -> dict:
    """修改角色设定（名称/性别/年龄/性格/背景/目标/状态/关系）"""
    project_id = params.get('project_id', '')
    character_id = params.get('character_id', '')
    name = params.get('name', '')
    gender = params.get('gender', '')
    age = params.get('age', '')
    personality = params.get('personality', '')
    background = params.get('background', '')
    goal = params.get('goal', '')
    status = params.get('status', '')
    relationship = params.get('relationship', '')

    if not project_id or not character_id:
        return _make_response(False, '缺少 project_id 或 character_id')

    r = await db.execute(
        select(Character).where(
            Character.id == character_id,
            Character.project_id == project_id,
        )
    )
    char = r.scalar_one_or_none()
    if not char:
        return _make_response(False, f'角色不存在: {character_id}')

    changed = []
    if name:
        char.name = name
        changed.append('name')
    if gender:
        char.gender = gender
        changed.append('gender')
    if age:
        char.age = age
        changed.append('age')
    if personality:
        char.personality = personality
        changed.append('personality')
    if background:
        char.background = background
        changed.append('background')
    if goal:
        char.goal = goal
        changed.append('goal')
    if status:
        char.status = status
        changed.append('status')
    if relationship:
        char.relationship = relationship
        changed.append('relationship')

    await db.commit()

    logger.info(f'PM更新角色: {char.name} {changed}')
    return _make_response(True, f'已更新角色「{char.name}」: {", ".join(changed)}', {'characters': {'name': char.name, 'updated_fields': changed}})


async def pm_update_character_state(params: dict, db) -> dict:
    """更新角色当前状态（位置/情绪/状态）"""
    character_id = params.get('character_id', '')
    state = params.get('state', '')
    if not character_id:
        return _make_response(False, '缺少 character_id')

    r = await db.execute(select(Character).where(Character.id == character_id))
    char = r.scalar_one_or_none()
    if not char:
        return _make_response(False, f'角色不存在: {character_id}')

    char.current_state = state
    await db.commit()

    logger.info(f'PM更新角色状态: {char.name} -> {state[:30]}')
    return _make_response(True, f'已更新角色「{char.name}」状态', {'characters': {'name': char.name, 'current_state': state}})


# =============================================================================
# 第2批（P2）：删类操作
# =============================================================================


async def pm_delete_chapter(params: dict, db) -> dict:
    """删除章节（软删除，将状态改为 deleted）"""
    chapter_id = params.get('chapter_id', '')
    if not chapter_id:
        return _make_response(False, '缺少 chapter_id')
    r = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = r.scalar_one_or_none()
    if not chapter:
        return _make_response(False, f'章节不存在：{chapter_id}')

    title = getattr(chapter, 'title', str(chapter_id))
    chapter_num = getattr(chapter, 'chapter_number', '?')
    stmt = update(Chapter).where(Chapter.id == chapter_id).values(status='deleted')
    await db.execute(stmt)
    await db.commit()

    logger.info(f'PMdel: ch{chapter_num} {title}')
    return _make_response(
        True,
        f'已删除第{chapter_num}章「{title}」',
        {
            'chapter_id': chapter_id,
            'chapter_number': chapter_num,
        },
    )


async def pm_delete_foreshadow(params: dict, db) -> dict:
    """删除伏笔"""
    foreshadow_id = params.get('foreshadow_id', '')
    if not foreshadow_id:
        return _make_response(False, '缺少 foreshadow_id')
    r = await db.execute(select(Foreshadow).where(Foreshadow.id == foreshadow_id))
    fs = r.scalar_one_or_none()
    title = getattr(fs, 'title', foreshadow_id) if fs else foreshadow_id
    if not fs:
        return _make_response(False, f'伏笔不存在：{foreshadow_id}')
    await db.execute(delete(Foreshadow).where(Foreshadow.id == foreshadow_id))
    await db.commit()

    logger.info(f'PMdelFS: {title}')
    return _make_response(True, f'已删除伏笔「{title}」', {'foreshadow_id': foreshadow_id})


async def pm_delete_subplot(params: dict, db) -> dict:
    """删除支线"""
    outline_id = params.get('outline_id', '')
    volume_order = safe_int(params.get('volume_order', 0), 0)
    subplot_id = params.get('subplot_id', '')

    if not outline_id or not subplot_id:
        return _make_response(False, '缺少 outline_id 或 subplot_id')
    r = await db.execute(select(Outline).where(Outline.id == outline_id))
    outline = r.scalar_one_or_none()
    if not outline:
        return _make_response(False, f'大纲不存在：{outline_id}')

    try:
        structure = safe_json_loads(outline.structure, {})
    except Exception:
        structure = {}

    volumes = structure.get('volumes', [])
    removed = False
    for vol in volumes:
        if vol.get('volume_order') == volume_order:
            subplots = vol.get('subplots', [])
            new_subplots = [s for s in subplots if s.get('id') != subplot_id]
            if len(new_subplots) < len(subplots):
                vol['subplots'] = new_subplots
                removed = True
            break

    if not removed:
        return _make_response(False, f'未找到支线 {subplot_id}')

    structure['volumes'] = volumes
    stmt = update(Outline).where(Outline.id == outline_id).values(structure=json.dumps(structure, ensure_ascii=False))
    await db.execute(stmt)
    await db.commit()

    logger.info(f'PMdelSub: {subplot_id}')
    return _make_response(
        True,
        f'已删除第{volume_order}卷支线 {subplot_id}',
        {
            'outline_id': outline_id,
            'subplot_id': subplot_id,
        },
    )
