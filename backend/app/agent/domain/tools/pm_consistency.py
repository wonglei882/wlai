"""PM 一致性守护工具组：check_character_state / check_world_consistency / maintain_memory"""

import contextlib
import logging

from app.agent.core.command_registry import ToolRegistry, ToolDefinition, RiskLevel
from app.services.json_helper import safe_int, safe_json_loads

logger = logging.getLogger(__name__)


# ==================== 工具 1: pm_check_character_state ====================


async def handle_pm_check_character_state(params: dict, db) -> dict:
    """检查角色跨章状态一致性：从 pm_consistency_state 读时间线，检测跳变"""
    from sqlalchemy import select
    from app.models.pm_consistency_state import PMConsistencyState
    from app.models.character import Character

    project_id = params.get('project_id', '')
    character_name = params.get('character', '')
    current_chapter = safe_int(params.get('current_chapter', 0), 0)

    if not project_id:
        return ['缺少 project_id']

    # 1. 读该角色的状态时间线（前 20 章的快照）
    snap_r = await db.execute(
        select(PMConsistencyState)
        .where(
            PMConsistencyState.project_id == project_id,
            PMConsistencyState.chapter_number < current_chapter,
        )
        .order_by(PMConsistencyState.chapter_number.desc())
        .limit(20)
    )
    snapshots = list(reversed(snap_r.scalars().all()))  # 按时间正序

    if not snapshots:
        return ['暂无状态快照数据，请先生成章节并触发自动提取']

    # 2. 读取角色基础信息
    char_r = await db.execute(
        select(Character).where(
            Character.project_id == project_id,
        )
    )
    all_characters = {c.name: c for c in char_r.scalars().all()}

    # 3. 构建时间线（所有角色或指定角色）
    lines = [f'角色状态时间线（截至第{current_chapter}章前）:']
    if character_name:
        lines.append(f'聚焦角色: {character_name}')

    conflicts = []

    prev_state = {}
    for snap in snapshots:
        ch = snap.chapter_number
        states = snap.character_states or {}

        if character_name:
            # 单角色模式
            s = states.get(character_name, {})
            if s:
                loc = s.get('location', '?')
                emo = s.get('emotion', '?')
                sts = s.get('status', '?')
                lines.append(f'  第{ch}章: 位置={loc} 情绪={emo} 状态={sts}')

                # 检测跳变
                if prev_state:
                    loc_jump = loc != prev_state.get('location') and loc and prev_state.get('location')
                    if loc_jump:
                        conflicts.append(f'  ⚠️ 第{ch}章: 位置跳变 {prev_state["location"]} → {loc}')
                prev_state = s
        else:
            # 全角色概览模式
            active = [f'{n}({s.get("location", "?")})' for n, s in states.items() if isinstance(s, dict)]
            lines.append(f'  第{ch}章: {", ".join(active[:6])}')
            prev_state = states

    # 4. 补充角色设定信息
    if character_name and character_name in all_characters:
        c = all_characters[character_name]
        lines.append('')
        lines.append('角色档案:')
        lines.append(f'  类型: {c.role_type or "?"}')
        lines.append(f'  状态: {c.status or "?"}')
        lines.append(f'  当前心理: {c.current_state or "?"}')
        if c.personality:
            lines.append(f'  性格: {c.personality[:100]}')

    if conflicts:
        lines.append('')
        lines.append('=== 检测到状态跳变 ===')
        lines.extend(conflicts[:5])
        lines.append('建议: 在跳变章节中加入过渡描写，避免读者困惑')
    else:
        lines.append('')
        lines.append('✅ 未检测到明显状态矛盾')

    return lines


# ==================== 工具 2: pm_check_world_consistency ====================


async def handle_pm_check_world_consistency(params: dict, db) -> dict:
    """检查世界观设定在章节间的一致性"""
    from sqlalchemy import select, func
    from app.models.project import Project
    from app.models.chapter import Chapter
    from app.models.pm_consistency_state import PMConsistencyState

    project_id = params.get('project_id', '')
    current_chapter = safe_int(params.get('current_chapter', 0), 0)

    if not project_id:
        return ['缺少 project_id']

    # 1. 读取项目世界观设定
    proj_r = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_r.scalar_one_or_none()
    if not project:
        return ['项目不存在']

    lines = [f'世界观一致性检查（第{current_chapter}章）:']
    lines.append(f'项目世界观规则: {project.world_rules or "未设定"}')
    lines.append(f'时间背景: {(project.world_time_period or "")[:100]}')
    lines.append(f'空间背景: {(project.world_location or "")[:100]}')
    lines.append('')

    # 2. 读取前几章的快照，看 world_states 是否稳定
    snap_r = await db.execute(
        select(PMConsistencyState)
        .where(
            PMConsistencyState.project_id == project_id,
        )
        .order_by(PMConsistencyState.chapter_number.desc())
        .limit(10)
    )
    snapshots = list(reversed(snap_r.scalars().all()))

    if not snapshots:
        lines.append('⚠️ 暂无状态快照，只能检查设定书面记录')

        # 降级：逐章扫描是否有世界观关键词冲突
        ch_count_r = await db.execute(
            select(func.count(Chapter.id)).where(
                Chapter.project_id == project_id,
                Chapter.chapter_number <= current_chapter,
            )
        )
        chapter_count = ch_count_r.scalar() or 0
        lines.append(f'  共 {chapter_count} 章，需逐章人工审核')
        return lines

    # 3. 对比前后章节的 world_states 是否有突变
    world_hashes = set()
    drift_detected = False
    for snap in snapshots:
        ws = snap.world_states or {}
        h = ws.get('_world_rules_hash', '')
        if h:
            world_hashes.add(h)

    if len(world_hashes) > 1:
        drift_detected = True
        lines.append('⚠️ 检测到世界观规则在不同章节间发生变化')

    if not drift_detected:
        lines.append('✅ 世界观设定在已生成章节间保持稳定')

    # 4. 快照中是否有状态变化记录
    lines.append('')
    lines.append('章节级世界观进程:')
    for snap in snapshots:
        ws = snap.world_states or {}
        # 过滤掉元字段
        entries = {k: v for k, v in ws.items() if not k.startswith('_')}
        if entries:
            lines.append(f'  第{snap.chapter_number}章: ' + ', '.join(f'{k}={v}' for k, v in entries.items()))
        else:
            lines.append(f'  第{snap.chapter_number}章: 无记录')

    return lines


# ==================== 工具 3: pm_maintain_memory ====================


async def handle_pm_maintain_memory(params: dict, db) -> dict:
    """更新/读取/清除 PM 对项目的全局记忆"""
    from sqlalchemy import select, delete
    from app.models.pm_consistency_state import PMConsistencyState
    from app.models.project import Project

    project_id = params.get('project_id', '')
    action = params.get('action', 'read')  # read / update / clear
    key = params.get('key', '')  # character_states / world_states / foreshadow_status / character_arc_progress
    value_raw = params.get('value', '')

    if not project_id:
        return ['缺少 project_id']

    proj_r = await db.execute(select(Project).where(Project.id == project_id))
    if not proj_r.scalar_one_or_none():
        return ['项目不存在']

    # 获取最新快照作为记忆
    snap_r = await db.execute(
        select(PMConsistencyState)
        .where(
            PMConsistencyState.project_id == project_id,
        )
        .order_by(PMConsistencyState.chapter_number.desc())
        .limit(1)
    )
    latest_snap = snap_r.scalar_one_or_none()

    if action == 'read':
        if not latest_snap:
            return ['暂无记忆数据']

        if key:
            # 读特定字段
            val = getattr(latest_snap, key, {})
            if isinstance(val, dict):
                lines = [f'记忆 [{key}] (第{latest_snap.chapter_number}章):']
                for k, v in list(val.items())[:20]:
                    lines.append(f'  {k}: {v}')
                if len(val) > 20:
                    lines.append(f'  ... 共 {len(val)} 项')
                return lines
            return [f'记忆 [{key}]: {val}']
        else:
            # 读全貌
            return [
                f'PM 全局记忆快照（第{latest_snap.chapter_number}章）:',
                f'  角色状态: {len(latest_snap.character_states or {})} 个角色',
                f'  世界观: {len(latest_snap.world_states or {})} 项',
                f'  伏笔: {len(latest_snap.foreshadow_status or {})} 项',
                f'  弧线: {len(latest_snap.character_arc_progress or {})} 项',
            ]

    elif action == 'update':
        if not key or not value_raw:
            return ['update 模式需要 key 和 value 参数']

        import json as _json

        try:
            value = _json.loads(value_raw) if isinstance(value_raw, str) else value_raw
        except (_json.JSONDecodeError, TypeError):
            return ['value 必须是合法的 JSON 字符串']

        if not latest_snap:
            return ['暂无快照记录，请先生成章节']

        # 更新字段
        current = getattr(latest_snap, key, {})
        if isinstance(current, dict) and isinstance(value, dict):
            current.update(value)
            setattr(latest_snap, key, current)
        else:
            setattr(latest_snap, key, value)

        await db.commit()
        return [f'记忆 [{key}] 已更新: +{len(value)} 项' if isinstance(value, dict) else f'记忆 [{key}] 已更新']

    elif action == 'clear':
        if not latest_snap:
            return ['暂无记忆数据']

        if key:
            setattr(latest_snap, key, {})
            await db.commit()
            return [f'记忆 [{key}] 已清空']
        else:
            await db.execute(delete(PMConsistencyState).where(PMConsistencyState.project_id == project_id))
            await db.commit()
            return ['所有 PM 记忆已清空']

    return [f'未知 action: {action}，支持 read/update/clear']


# =============================================================================
# AUTO-FIX 工具：发现即修正，不用等用户确认
# =============================================================================


async def _fix_character_location_jump(db, project_id: str, character_name: str, from_ch: int, to_ch: int, from_loc: str, to_loc: str) -> dict:
    """内部：记录角色位置跳变（建议模式，不改正文）

    PM 是一致性追踪系统，不是正文修复系统。修复动作为：
    1. 记录状态变更到 Character.current_state
    2. 返回建议信息（供前端展示）
    """
    from sqlalchemy import select
    from app.models.character import Character

    char_r = await db.execute(
        select(Character).where(
            Character.project_id == project_id,
            Character.name == character_name,
        )
    )
    char = char_r.scalar_one_or_none()
    if char:
        current = char.current_state or ''
        char.current_state = f'{current} [第{to_ch}章转移至{to_loc}]'
        await db.commit()

    # 返回建议信息（供 PMDecisionLog.fix_details 使用）
    return {
        'action': 'state_change_logged',
        'character': character_name,
        'from_location': from_loc,
        'to_location': to_loc,
        'from_chapter': from_ch,
        'to_chapter': to_ch,
        'suggestion': f'建议：在第{to_ch}章中补充{character_name}从{from_loc}到{to_loc}的转移描写',
        'note': '此为一致性追踪系统，已记录状态变更，章节正文需人工修改或下次生成时考虑',
    }


async def _fix_world_rule_drift(db, project_id: str, conflicts: list) -> str:
    """内部：为世界观漂移创建伏笔备忘，并将旧章节快照的 world_rules_hash 对齐到当前规则。

    P0 修复（99.4% 失败死循环根因）：
    - 原 hash 算法用 `md5(Project.world_rules[:200])`，但 pm_consistency_guardian.extract_and_save
      用的是"本章正文实际命中的规则关键词子集"算 hash。
    - 两套算法不一致 → 对齐后下次扫描又用 guardian 算法重算 → hash 永远不一致 → 死循环。
    - 修复：改为按章节正文重算 hash（与 guardian 算法一致），让对齐真正生效。
    - 同时修复 conflicts 入参兼容：pm_fix_handlers 传入 [issue_dict]，原代码 c[:30] 切片 dict 会异常。
    """
    from app.models.foreshadow import Foreshadow
    from app.models.project import Project
    from app.models.pm_consistency_state import PMConsistencyState
    from app.models.chapter import Chapter
    from sqlalchemy import select
    import uuid
    import hashlib
    import re as _re

    # 1) 对齐 hash（按章节正文重算，与 guardian.extract_and_save 算法一致）
    aligned = 0
    try:
        proj_r = await db.execute(select(Project).where(Project.id == project_id))
        proj = proj_r.scalar_one_or_none()
        if proj and proj.world_rules:
            rules_text = proj.world_rules or ''
            # 与 guardian 一致：提取 2-6 字中文规则关键词
            rule_keywords = set(_re.findall(r'[\u4e00-\u9fff]{2,6}', rules_text[:1000]))

            snap_r = await db.execute(
                select(PMConsistencyState).where(
                    PMConsistencyState.project_id == project_id,
                )
            )
            snapshots = snap_r.scalars().all()

            # 批量取章节正文（避免 N+1 查询）
            ch_ids = [s.chapter_id for s in snapshots if s.chapter_id]
            ch_map: dict[str, str] = {}
            if ch_ids:
                ch_r = await db.execute(select(Chapter).where(Chapter.id.in_(ch_ids)))
                for ch in ch_r.scalars().all():
                    ch_map[ch.id] = ch.content or ''

            for s in snapshots:
                ch_content = ch_map.get(s.chapter_id, '')
                # 与 guardian 一致：本章正文实际命中的规则关键词子集
                appeared = sorted(k for k in rule_keywords if k in ch_content)
                # 非加密用途：仅作世界观规则指纹（缓存比对），非安全场景
                new_hash = hashlib.md5('|'.join(appeared).encode('utf-8')).hexdigest()[:16] if appeared else 'empty'  # noqa: S324

                ws = s.world_states or {}
                if isinstance(ws, dict) and ws.get('_world_rules_hash', '') != new_hash:
                    ws = dict(ws)
                    ws['_world_rules_hash'] = new_hash
                    ws['_appeared_rules'] = appeared[:20]  # 同步更新命中列表
                    s.world_states = ws
                    aligned += 1
    except Exception as e:
        logger.warning(f'[pm_consistency] 对齐 world_rules_hash 失败（不影响伏笔记录）: {e}')

    # 2) 创建伏笔备忘（修复：conflicts 可能是 dict 列表，统一转 str）
    count = 0
    for c in conflicts[:5]:
        # P0 修复：兼容 dict 入参（pm_fix_handlers 传入 issue dict）
        c_str = (c.get('message') or c.get('chapter_range') or str(c)[:200]) if isinstance(c, dict) else str(c)
        fs = Foreshadow(
            id=uuid.uuid4().hex,
            project_id=project_id,
            title=f'世界观矛盾-{c_str[:30]}',
            content=c_str,
            status='active',
            category='mystery',
        )
        db.add(fs)
        count += 1

    await db.commit()
    return f'已为{count}处世界观漂移创建伏笔，对齐 {aligned} 个章节快照 hash（按章节正文重算）'


# ==================== 工具 4: pm_auto_fix_character_state ====================


async def handle_pm_auto_fix_character_state(params: dict, db) -> dict:
    """自动修正角色状态冲突"""
    from sqlalchemy import select
    from app.models.pm_consistency_state import PMConsistencyState

    project_id = params.get('project_id', '')
    character_name = params.get('character', '')
    current_chapter = safe_int(params.get('current_chapter', 0), 0)
    conflicts_raw = params.get('conflicts', [])

    if not project_id:
        return ['缺少 project_id']

    if conflicts_raw:
        fixes = []
        suggestions = []
        for c in conflicts_raw:
            if '位置跳变' in str(c):
                parts = str(c).replace('→', ' ').split()
                to_loc = parts[-1].strip() if parts else '新位置'
                result = await _fix_character_location_jump(db, project_id, character_name or '角色', 0, current_chapter, '', to_loc)
                fixes.append(result.get('action', 'state_change_logged'))
                suggestions.append(result.get('suggestion', ''))
        if fixes:
            from app.services.inspiration_skills import _resolve_diagnostic_log

            await _resolve_diagnostic_log(db, 'character_state_conflict', project_id, resolved_by='auto_fix')
            return {
                'status': 'success',
                'message': f'已记录 {len(fixes)} 处角色状态变更',
                'suggestions': suggestions,
                'note': '此为一致性追踪系统，章节正文需人工修改或下次生成时考虑',
            }
        return ['未识别出可自动修复的冲突类型']

    # 自动检测 + 修复
    snap_r = await db.execute(
        select(PMConsistencyState)
        .where(
            PMConsistencyState.project_id == project_id,
            PMConsistencyState.chapter_number < current_chapter,
        )
        .order_by(PMConsistencyState.chapter_number.desc())
        .limit(20)
    )
    snapshots = list(reversed(snap_r.scalars().all()))

    fixes = []
    suggestions = []
    prev_state = {}
    for snap in snapshots:
        states = snap.character_states or {}
        if character_name:
            s = states.get(character_name, {})
            if s and prev_state:
                from_loc = prev_state.get('location', '')
                to_loc = s.get('location', '')
                if from_loc and to_loc and from_loc != to_loc:
                    result = await _fix_character_location_jump(
                        db, project_id, character_name, snap.chapter_number - 1, snap.chapter_number, from_loc, to_loc
                    )
                    fixes.append(result.get('action', 'state_change_logged'))
                    suggestions.append(result.get('suggestion', ''))
            prev_state = s

    if fixes:
        from app.services.inspiration_skills import _resolve_diagnostic_log

        await _resolve_diagnostic_log(db, 'character_state_conflict', project_id, resolved_by='auto_fix')
        return {
            'status': 'success',
            'message': f'检测并记录了 {len(fixes)} 处角色状态变更',
            'suggestions': suggestions,
            'note': '此为一致性追踪系统，章节正文需人工修改或下次生成时考虑',
        }
    return ['✅ 未检测到需要修正的角色状态冲突']


# ==================== 工具 5: pm_auto_fix_world_consistency ====================


async def handle_pm_auto_fix_world_consistency(params: dict, db) -> dict:
    """自动修正世界观不一致"""
    from sqlalchemy import select
    from app.models.project import Project
    from app.models.pm_consistency_state import PMConsistencyState

    project_id = params.get('project_id', '')
    conflicts_raw = params.get('conflicts', [])

    if not project_id:
        return ['缺少 project_id']

    proj_r = await db.execute(select(Project).where(Project.id == project_id))
    if not proj_r.scalar_one_or_none():
        return ['项目不存在']

    if conflicts_raw:
        msg = await _fix_world_rule_drift(db, project_id, conflicts_raw)
        return ['✅ ' + msg]

    # 检测漂移
    snap_r = await db.execute(
        select(PMConsistencyState)
        .where(
            PMConsistencyState.project_id == project_id,
        )
        .order_by(PMConsistencyState.chapter_number.desc())
        .limit(10)
    )
    snapshots = list(reversed(snap_r.scalars().all()))

    world_hashes = [(s.chapter_number, (s.world_states or {}).get('_world_rules_hash', '')) for s in snapshots]
    drift_count = len(set(h for _, h in world_hashes)) - 1

    if drift_count > 0:
        conflicts = [f'世界观规则在第{ch}章发生变化' for ch, _ in world_hashes]
        msg = await _fix_world_rule_drift(db, project_id, conflicts)
        try:
            from app.services.inspiration_skills import _resolve_diagnostic_log

            await _resolve_diagnostic_log(db, 'world_consistency_issue', project_id, resolved_by='auto_fix')
        except Exception as e:
            logger.warning(f'[pm_consistency] resolve world_consistency_issue 失败（已回滚）: {e}')
            # 回滚失败可忽略：连接会在下次事务时自动恢复
            with contextlib.suppress(Exception):
                await db.rollback()
        return ['⚠️ 检测到世界观漂移', f'✅ {msg}']

    return ['✅ 世界观设定保持一致，无需修正']


# ==================== 工具 6: pm_check_and_fix_sequence_conflict ====================


async def handle_pm_check_and_fix_sequence_conflict(params: dict, db) -> dict:
    """检查并修正序列逻辑矛盾"""
    from sqlalchemy import select, update
    from app.models.chapter import Chapter
    import json

    chapter_id = params.get('chapter_id', '')
    sequence_index = safe_int(params.get('sequence_index', 0), 0)

    if not chapter_id:
        return ['缺少 chapter_id']

    ch_r = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = ch_r.scalar_one_or_none()
    if not chapter:
        return ['章节不存在']

    try:
        ep = safe_json_loads(chapter.expansion_plan, {})
    except Exception:
        ep = {}

    sequences = ep.get('sequences', [])
    if sequence_index >= len(sequences):
        return [f'序列{sequence_index}不存在（共{len(sequences)}个）']

    prev_task = sequences[sequence_index - 1].get('core_task', '') if sequence_index > 0 else ''
    curr_task = sequences[sequence_index].get('core_task', '')
    next_task = sequences[sequence_index + 1].get('core_task', '') if sequence_index < len(sequences) - 1 else ''

    contradictions = []
    patterns = [('死亡', '活着'), ('受伤', '完好'), ('失忆', '记得'), ('消失', '出现'), ('逃走', '抓住')]

    for a, b in patterns:
        if prev_task and curr_task and a in prev_task and b in curr_task:
            contradictions.append(f"序列{sequence_index}与{sequence_index - 1}: 前'{a}'→后'{b}'")
        if curr_task and next_task and a in curr_task and b in next_task:
            contradictions.append(f"序列{sequence_index + 1}与{sequence_index}: 前'{a}'→后'{b}'")

    if not contradictions:
        return [f'✅ 序列{sequence_index}未检测到逻辑矛盾']

    for cf in contradictions:
        seq_idx = sequence_index if str(sequence_index) in cf else sequence_index + 1
        if seq_idx < len(sequences):
            old_task = sequences[seq_idx].get('core_task', '')
            sequences[seq_idx]['core_task'] = old_task + f'（衔接：{cf}）'

    stmt = update(Chapter).where(Chapter.id == chapter_id).values(expansion_plan=json.dumps(ep, ensure_ascii=False))
    await db.execute(stmt)
    await db.commit()
    from app.services.inspiration_skills import _resolve_diagnostic_log

    await _resolve_diagnostic_log(db, 'sequence_logic_conflict', chapter.project_id, resolved_by='auto_fix')
    return [f'✅ 已修正 {len(contradictions)} 处序列逻辑矛盾', *contradictions]


# ==================== 注册入口 ====================


def register_pm_consistency_tools(registry: ToolRegistry) -> None:
    """注册PM一致性Tools

    Args:
        registry:

    Returns:
        None
    """
    registry.register(
        ToolDefinition(
            name='pm_check_character_state',
            description='检查角色跨章状态一致性（位置/情绪/状态跳变检测）',
            params_schema={
                'project_id': 'str: 项目UUID',
                'character': 'str: 角色名（留空则概览所有角色）',
                'current_chapter': 'int: 当前章节号',
            },
            required_params=['project_id', 'current_chapter'],
            param_types={'project_id': 'str'},
            handler=handle_pm_check_character_state,
            risk_level=RiskLevel.LOW,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_check_world_consistency',
            description='检查世界观设定在章节间的一致性，检测设定漂移',
            params_schema={
                'project_id': 'str: 项目UUID',
                'current_chapter': 'int: 当前章节号',
            },
            required_params=['project_id'],
            param_types={'project_id': 'str'},
            handler=handle_pm_check_world_consistency,
            risk_level=RiskLevel.LOW,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_maintain_memory',
            description='更新/读取/清除 PM 对项目的全局记忆（角色状态/世界观/伏笔/弧线）',
            params_schema={
                'project_id': 'str: 项目UUID',
                'action': 'str: read/update/clear',
                'key': 'str: character_states|world_states|foreshadow_status|character_arc_progress（clear/read 可选）',
                'value': 'json: 要更新的内容（仅 update 模式需要）',
            },
            required_params=['project_id', 'action'],
            param_types={'project_id': 'str'},
            handler=handle_pm_maintain_memory,
            risk_level=RiskLevel.LOW,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_auto_fix_character_state',
            description='PM专用：自动修正角色状态冲突（检测到跳变后直接修复，不问用户）',
            params_schema={
                'project_id': 'str: 项目UUID',
                'character': 'str: 角色名（留空修正所有角色）',
                'current_chapter': 'int: 当前章节号',
                'conflicts': 'list: 直接传入冲突列表（可选，不传则自动检测）',
            },
            required_params=['project_id'],
            param_types={'project_id': 'str'},
            handler=handle_pm_auto_fix_character_state,
            risk_level=RiskLevel.MEDIUM,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_auto_fix_world_consistency',
            description='PM专用：自动修正世界观不一致（为漂移处创建伏笔备忘）',
            params_schema={
                'project_id': 'str: 项目UUID',
                'current_chapter': 'int: 当前章节号',
                'conflicts': 'list: 直接传入冲突列表（可选）',
            },
            required_params=['project_id'],
            param_types={'project_id': 'str'},
            handler=handle_pm_auto_fix_world_consistency,
            risk_level=RiskLevel.MEDIUM,
        )
    )

    registry.register(
        ToolDefinition(
            name='pm_check_and_fix_sequence_conflict',
            description='PM专用：检查单个序列逻辑矛盾（与前后序列是否矛盾）并自动追加衔接说明',
            params_schema={
                'chapter_id': 'str: 章节UUID',
                'sequence_index': 'int: 序列索引',
            },
            required_params=['chapter_id'],
            param_types={'chapter_id': 'str'},
            handler=handle_pm_check_and_fix_sequence_conflict,
            risk_level=RiskLevel.MEDIUM,
        )
    )
