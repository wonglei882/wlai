"""PM 写操作工具集 — AI 生成操作（第2批）

由 pm_write_operations.py 拆分而来（god file 专项重构）。
"""

from app.agent.domain.tools.pm_write_base import _make_response, logger, safe_int, safe_json_loads
import json
import re
import uuid
from sqlalchemy import select, update
from app.models.chapter import Chapter
from app.models.outline import Outline
from app.models.project import Project

# 第2批（P2）：生成类操作
# =============================================================================


async def pm_generate_volume_outlines(params: dict, db) -> dict:
    """AI生成分卷大纲，写入 Outline.structure.volumes"""
    outline_id = params.get('outline_id', '')
    volume_count = safe_int(params.get('volume_count', 3), 3)

    if not outline_id:
        return _make_response(False, '缺少 outline_id')
    r = await db.execute(select(Outline).where(Outline.id == outline_id))
    outline = r.scalar_one_or_none()
    if not outline:
        return _make_response(False, f'大纲不存在：{outline_id}')

    proj_r = await db.execute(select(Project).where(Project.id == outline.project_id))
    project = proj_r.scalar_one_or_none()
    theme = project.theme if project else ''
    title = project.title if project else ''

    prompt_lines = [
        f'为小说「{title}」（主题：{theme}）设计{volume_count}卷大纲。',
        '输出JSON数组，每个元素包含：volume_order(int), volume_title(str), volume_theme(str), '
        'volume_goal(str), chapters(数组,每个有chapter_order和title)。',
        '只输出JSON。',
    ]
    prompt = chr(10).join(prompt_lines)

    from app.services.ai.ai_service import AIService

    ai = AIService()
    resp = await ai.generate_text(prompt=prompt, temperature=0.5, auto_mcp=False)
    raw = str(resp.get('content', '')) if isinstance(resp, dict) else str(resp)
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    if not m:
        return _make_response(False, 'AI 未返回有效 JSON')
    new_volumes = safe_json_loads(m.group(0), [])

    try:
        structure = safe_json_loads(outline.structure, {})
    except Exception:
        structure = {}
    structure['volumes'] = new_volumes
    stmt = update(Outline).where(Outline.id == outline_id).values(structure=json.dumps(structure, ensure_ascii=False))
    await db.execute(stmt)
    await db.commit()

    logger.info(f'PMgenVol: {len(new_volumes)}卷')
    return _make_response(
        True,
        f'已生成{len(new_volumes)}卷大纲',
        {
            'outline_id': outline_id,
            'volumes_generated': len(new_volumes),
        },
    )


async def pm_generate_pacing_suggestion(params: dict, db) -> dict:
    """AI为章节生成节奏建议"""
    chapter_id = params.get('chapter_id', '')
    if not chapter_id:
        return _make_response(False, '缺少 chapter_id')
    r = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = r.scalar_one_or_none()
    if not chapter:
        return _make_response(False, f'章节不存在：{chapter_id}')

    ch_num = getattr(chapter, 'chapter_number', '?')
    try:
        ep = safe_json_loads(chapter.expansion_plan, {})
    except Exception:
        ep = {}
    sequences = ep.get('sequences', [])
    seq_parts = [f'S{i}: {s.get("core_task", "")}' for i, s in enumerate(sequences[:8])]
    seq_text = chr(10).join(seq_parts)

    prompt_lines = [
        f'为第{ch_num}章生成节奏建议。当前序列规划：{seq_text}',
        '请为每个序列标注：节奏类型(铺垫/发展/高潮/回落)、建议段落长度。',
        '输出JSON数组：[{sequence:int, pacing:str, suggestion:str, target_words:int}]',
        '只输出JSON。',
    ]
    prompt = chr(10).join(prompt_lines)

    from app.services.ai.ai_service import AIService

    ai = AIService()
    resp = await ai.generate_text(prompt=prompt, temperature=0.5, auto_mcp=False)
    raw = str(resp.get('content', '')) if isinstance(resp, dict) else str(resp)
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    if not m:
        return _make_response(False, 'AI 未返回有效节奏建议')
    suggestions = safe_json_loads(m.group(0), [])

    logger.info(f'PMpace: ch{ch_num} {len(suggestions)}个')
    return _make_response(
        True,
        f'已生成{len(suggestions)}个节奏建议',
        {
            'chapter_id': chapter_id,
            'chapter_number': ch_num,
            'suggestions': suggestions,
        },
    )


async def pm_suggest_conflict(params: dict, db) -> dict:
    """AI推荐当前卷的核心冲突点"""
    project_id = params.get('project_id', '')
    volume_order = safe_int(params.get('volume_order', 1), 1)

    if not project_id:
        return _make_response(False, '缺少 project_id')
    proj_r = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_r.scalar_one_or_none()
    theme = project.theme if project else ''
    title = project.title if project else ''

    # 读取最近3章了解当前进度
    ch_r = await db.execute(
        select(Chapter)
        .where(
            Chapter.project_id == project_id,
            Chapter.status == 'published',
        )
        .order_by(Chapter.chapter_number.desc())
        .limit(3)
    )
    recent = list(reversed(list(ch_r.scalars().all())))
    recent_parts = [f'第{getattr(c, "chapter_number", "?")}章：{getattr(c, "title", "")[:50]}' for c in recent]
    recent_text = chr(10).join(recent_parts) if recent_parts else '暂无已发布章节'

    prompt_lines = [
        f'为小说「{title}」（主题：{theme}）第{volume_order}卷推荐3-5个核心冲突点。',
        f'最近章节进度：{recent_text}',
        '输出JSON数组：[{type:str, description:str, escalation:str}]',
        '只输出JSON。',
    ]
    prompt = chr(10).join(prompt_lines)

    from app.services.ai.ai_service import AIService

    ai = AIService()
    resp = await ai.generate_text(prompt=prompt, temperature=0.6, auto_mcp=False)
    raw = str(resp.get('content', '')) if isinstance(resp, dict) else str(resp)
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    if not m:
        return _make_response(False, 'AI 未返回有效冲突建议')
    conflicts = safe_json_loads(m.group(0), [])

    logger.info(f'PMconf: {len(conflicts)}个')
    return _make_response(
        True,
        f'已生成{len(conflicts)}个冲突建议',
        {
            'project_id': project_id,
            'volume_order': volume_order,
            'conflicts': conflicts,
        },
    )


async def pm_create_chapter_with_plan(params: dict, db) -> dict:
    """创建章节并自动生成8序列规划（一步完成）"""
    project_id = params.get('project_id', '')
    chapter_number = safe_int(params.get('chapter_number', 1), 1)
    title = params.get('title', f'第{chapter_number}章')

    if not project_id:
        return _make_response(False, '缺少 project_id')

    prompt_lines = [
        f'为小说第{chapter_number}章「{title}」设计8个标准序列规划。',
        '8序列标签固定：铺垫/触发/探索/升级/高潮/回落/解决/尾声。',
        '每个序列输出：core_task(20字内)、target_words(目标字数)。',
        '输出JSON：{sequences: [{label:str, core_task:str, target_words:int}]}',
        '只输出JSON。',
    ]
    prompt = chr(10).join(prompt_lines)

    from app.services.ai.ai_service import AIService

    ai = AIService()
    resp = await ai.generate_text(prompt=prompt, temperature=0.5, auto_mcp=False)
    raw = str(resp.get('content', '')) if isinstance(resp, dict) else str(resp)
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        return _make_response(False, 'AI 未返回有效序列规划')
    plan = safe_json_loads(m.group(0), {})
    sequences = plan.get('sequences', [])

    if not sequences:
        return _make_response(False, 'AI 返回的序列为空')

    chapter_id = str(uuid.uuid4())
    ep = {'sequences': sequences, 'sequence_outcomes': []}
    chapter = Chapter(
        id=chapter_id,
        project_id=project_id,
        chapter_number=chapter_number,
        title=title,
        status='draft',
        expansion_plan=json.dumps(ep, ensure_ascii=False),
    )
    db.add(chapter)
    await db.commit()

    logger.info(f'PMcreateCh: ch{chapter_number} {len(sequences)}个序列')
    return _make_response(
        True,
        f'已创建第{chapter_number}章并规划{len(sequences)}个序列',
        {
            'chapter_id': chapter_id,
            'chapter_number': chapter_number,
            'sequences_count': len(sequences),
        },
    )
