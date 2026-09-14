"""PM 修复执行器 — 从 pm_fix_handlers.py 拆分。

为控制 pm_fix_handlers.py 行数（原 1148 行 > 800 红线），将所有 _fix_* 修复执行函数拆到此模块。
pm_fix_handlers.py 保留：工具函数（失败分类/实体提取/目标偏离）、_execute_fix、验证、注册。

依赖方向：pm_fix_handlers.py → pm_fix_executors.py（单向，无循环）
"""

from typing import Any

from sqlalchemy import select

import logging
from app.services.pm.feature_config import is_pm_feature_enabled

logger = logging.getLogger(__name__)


# =============================================================================
# 核心修复 handler（角色/世界观/伏笔/质量分）
# =============================================================================


async def _fix_character_location(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """修复角色位置跳变 — 调用 handle_pm_auto_fix_character_state。"""
    from app.agent.domain.tools.pm_consistency import handle_pm_auto_fix_character_state

    current_ch = issue.get('from_chapter', 0) or 0

    await handle_pm_auto_fix_character_state(
        {'project_id': project_id, 'current_chapter': current_ch, 'violations': [issue]},
        db,
    )
    return f'角色位置一致性已修复（第{current_ch}章）'


async def _fix_world_rule_drift(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """修复世界观漂移 — 规则保底(hash 对齐+建伏笔) + LLM 建议模式。

    P0 折中方案：
    - 规则修复保底：对齐 hash + 建伏笔（已落地）
    - LLM 建议：按最新 world_rules 生成漂移章节修改建议，写入 PMDecisionLog.fix_details，
      用户可在修复报告中查看并决定是否采纳。不直接改正文。
    """
    from app.agent.domain.tools.pm_consistency import handle_pm_auto_fix_world_consistency
    from app.models.project import Project
    from app.models.chapter import Chapter

    current_ch = issue.get('from_chapter', 0) or 0

    # 1. 规则修复保底（hash 对齐 + 建伏笔）
    await handle_pm_auto_fix_world_consistency(
        {'project_id': project_id, 'current_chapter': current_ch, 'violations': [issue]},
        db,
    )

    # 2. LLM 分析漂移并更新 world_rules 正文（根治而非只对齐 hash）
    llm_suggestion = ''
    # 功能启用检查：world_drift 的 LLM 建议是 optional 功能
    if not is_pm_feature_enabled('optional.world_drift_llm_fix'):
        logger.debug('[PM-Agent] world_drift LLM 根因修复未启用（optional.world_drift_llm_fix disabled）')
    else:
        try:
            # 取最新 world_rules
            proj_r = await db.execute(select(Project).where(Project.id == project_id))
            proj = proj_r.scalar_one_or_none()
            world_rules = (proj.world_rules or '')[:500] if proj else ''

            # 取漂移章节内容摘要
            ch_r = await db.execute(
                select(Chapter)
                .where(
                    Chapter.project_id == project_id,
                    Chapter.chapter_number == current_ch,
                )
                .limit(1)
            )
            ch = ch_r.scalar_one_or_none()
            ch_content = (ch.content or '')[:800] if ch else ''

            if world_rules and ch_content:
                from app.services.pm.pm_ai_client import get_pm_ai_client
                from app.services.pm.pm_llm_guard import call_llm_with_guard

                ai_service = await get_pm_ai_client(user_id, db)
                if ai_service is not None:
                    # P0 升级：让 LLM 分析章节中的新设定，并更新 world_rules 正文
                    prompt = f"""你是小说世界观一致性专家。以下是当前世界观规则和第{current_ch}章片段。

【当前世界观规则】
{world_rules}

【第{current_ch}章片段】
{ch_content}

章节中可能引入了新的世界观要素（新地点、新规则、新设定），或者与现有规则有冲突。

请执行以下任务：
1. 找出章节中引入的新设定或与现有规则冲突的地方
2. 给出更新后的世界观规则全文（将新设定整合进现有规则，修正冲突项）

格式：
分析：...
更新后规则：...（完整的更新后世界观规则正文）"""

                    from app.services.pm.pm_token_budget import BudgetContext

                    result = await call_llm_with_guard(
                        ai_service.generate_text,
                        breaker_name='world_drift_fix',
                        prompt=prompt,
                        max_tokens=800,
                        temperature=0.3,
                        budget_ctx=BudgetContext(user_id=user_id, project_id=project_id, feature='repair', action='world_drift', db=db),
                    )
                    if result:
                        llm_suggestion = (result.get('content') or '').strip()

                        # 提取"更新后规则"部分，更新 projects.world_rules
                        if '更新后规则：' in llm_suggestion:
                            new_rules = llm_suggestion.split('更新后规则：', 1)[1].strip()
                            if new_rules and len(new_rules) > 50:  # 确保有实质内容
                                from sqlalchemy import update as _upd

                                await db.execute(_upd(Project).where(Project.id == project_id).values(world_rules=new_rules[:2000]))
                                logger.info(f'[PM-Agent] world_rules 已更新（项目={project_id}）')
                                llm_suggestion = llm_suggestion[:500]  # 截断用于 fix_details
        except Exception as e:
            logger.warning(f'[PM-Agent] LLM 建议生成失败（非阻断）: {e}')

    # 3. resolve 同类诊断
    try:
        from app.services.inspiration_sub.diagnostic import _resolve_diagnostic_log

        await _resolve_diagnostic_log(db, 'world_rule_drift', project_id, 'auto_fix')
        await _resolve_diagnostic_log(db, 'pm_agent_world_drift', project_id, 'auto_fix')
    except Exception as e:
        logger.debug(f'[PM-Agent] resolve world_rule_drift 失败: {e}')

    # 4. 返回结果（含 LLM 建议，供 fix_details 记录）
    base_msg = '世界观一致性已尝试修复（hash 对齐 + 建伏笔）'
    if llm_suggestion:
        return f'{base_msg}\n【LLM 建议】\n{llm_suggestion}'
    return base_msg


async def _fix_foreshadow_stale(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """处理伏笔老化 — 标记 stale + 生成回收建议。

    P0 升级：
    - 原逻辑只标记 stale（100% success 但没真正回收）
    - 新增 LLM 生成回收建议（可选功能），写入 fix_action 供用户参考
    """
    from app.models.foreshadow import Foreshadow

    fs_id = issue.get('foreshadow_id', '')
    if not fs_id:
        return '伏笔老化处理跳过（无 foreshadow_id）'

    fs_r = await db.execute(select(Foreshadow).where(Foreshadow.id == fs_id))
    foreshadow = fs_r.scalar_one_or_none()
    if not foreshadow:
        return f'伏笔 {fs_id} 不存在'

    # 标记 stale
    foreshadow.status = 'stale'
    foreshadow.urgency = 2

    # 计算回收建议章节
    planted_ch = foreshadow.plant_chapter_number or 0
    latest_ch_r = await db.execute(
        select(Foreshadow).where(Foreshadow.project_id == project_id).order_by(Foreshadow.plant_chapter_number.desc()).limit(1)
    )
    latest_ch = latest_ch_r.scalar_one_or_none()
    latest_chapter = (latest_ch.plant_chapter_number if latest_ch else 0) or planted_ch + 10
    suggested_ch = max(latest_chapter + 1, planted_ch + 5)

    # 生成 LLM 回收建议
    recovery_suggestion = ''
    if is_pm_feature_enabled('optional.self_evolution'):
        try:
            from app.services.pm.pm_ai_client import get_pm_ai_client
            from app.services.pm.pm_llm_guard import call_llm_with_guard

            ai_service = await get_pm_ai_client(user_id, db)
            if ai_service is not None:
                prompt = f"""你是小说创作顾问。以下伏笔已埋设{latest_chapter - planted_ch}章但未回收，需要给出回收建议。

【伏笔标题】{foreshadow.title}
【伏笔内容】{(foreshadow.content or '')[:300]}
【埋设章节】第{planted_ch}章
【当前章节】第{latest_chapter}章
【建议回收章节】第{suggested_ch}章

请给出具体的回收方案（3-5句话）：
1. 在第{suggested_ch}章的什么情节场景中回收最自然
2. 回收时如何呼应埋设时的暗示
3. 回收后对角色/剧情的影响

格式：回收方案：..."""

                from app.services.pm.pm_token_budget import BudgetContext

                result = await call_llm_with_guard(
                    ai_service.generate_text,
                    breaker_name='foreshadow_recovery',
                    prompt=prompt,
                    max_tokens=400,
                    temperature=0.4,
                    budget_ctx=BudgetContext(user_id=user_id, project_id=project_id, feature='repair', action='foreshadow_recovery', db=db),
                )
                if result:
                    recovery_suggestion = (result.get('content') or '').strip()[:500]
        except Exception as e:
            logger.warning(f'[PM-Agent] 伏笔回收建议生成失败（非阻断）: {e}')

    # 构建返回消息
    base_msg = f'伏笔「{foreshadow.title}」已标记为 stale（urgency=2）'
    if recovery_suggestion:
        return f'{base_msg}\n【回收建议】建议在第{suggested_ch}章回收\n{recovery_suggestion}'
    return f'{base_msg}\n【回收建议】建议在第{suggested_ch}章回收（LLM 建议未生成，请人工规划回收方案）'


def _as_int(value, default: int = 0) -> int:
    """稳健转 int：兼容 int / 数字字符串 / None，解析失败回退 default。"""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default
    return default


async def _fix_quality_low(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """处理质量分低 — 触发 PM 一致性检查 + 自动修复。"""
    from app.services.core.event_bus_listeners import _auto_run_consistency_check

    # 章节号优先取 issue.chapter_number（total_score 是质量分而非章节号，不能兜底）
    chapter_number = issue.get('chapter_number') or 0
    ch_num = _as_int(chapter_number)

    # 获取实际章节 ID（从 chapter_number 反查，或直接用 chapter_id 参数）
    from app.models.chapter import Chapter

    ch_result = await db.execute(
        select(Chapter.id)
        .where(
            Chapter.project_id == project_id,
            Chapter.chapter_number == ch_num,
        )
        .order_by(Chapter.created_at.desc())
        .limit(1)
    )
    chapter_id_row = ch_result.first()
    if not chapter_id_row:
        return f'质量分低修复跳过（章节 {ch_num} 不存在）'

    chapter_id = chapter_id_row[0]

    # 触发一致性检查（会自动修复角色/世界观问题）
    # 注：签名 (db, chapter_id, project_id, user_id)，勿调换顺序
    try:
        await _auto_run_consistency_check(db, chapter_id, project_id, user_id)
    except Exception as e:
        logger.warning(f'[PM-Agent] 质量分修复 - 一致性检查失败: {e}')

    return f'质量分低已触发一致性检查（第{ch_num}章）'


# =============================================================================
# P0.2: 段落格式修复 -- 调用 format_webnovel_paragraphs 重排超长段落
# =============================================================================


async def _fix_paragraph_format(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    # 段落格式修复: 对超长段落执行 format_webnovel_paragraphs 重排
    from app.models.chapter import Chapter

    chapter_number = issue.get('chapter_number') or 0
    ch_num = _as_int(chapter_number, 0)

    ch_result = await db.execute(
        select(Chapter)
        .where(
            Chapter.project_id == project_id,
            Chapter.chapter_number == ch_num,
        )
        .order_by(Chapter.created_at.desc())
        .limit(1)
    )
    chapter = ch_result.scalar_one_or_none()
    if not chapter:
        return f'段落格式修复跳过（章节 {ch_num} 不存在）'

    content = chapter.content or ''
    if not content.strip():
        return f'段落格式修复跳过（章节 {ch_num} 内容为空）'

    try:
        from app.api.chapters._helpers._format import format_webnovel_paragraphs

        formatted = format_webnovel_paragraphs(content)
        if formatted == content:
            return f'段落格式修复跳过（章节 {ch_num} 已合规）'

        chapter.content = formatted
        chapter.word_count = len(formatted)
        await db.flush()

        old_long = len([p for p in content.split('\n\n') if len(p.strip()) > 110])
        new_long = len([p for p in formatted.split('\n\n') if len(p.strip()) > 110])

        return f'段落格式修复完成（第{ch_num}章）：超长段落 {old_long} -> {new_long}'
    except Exception as e:
        logger.warning(f'[PM-Agent] 段落格式修复失败: {e}')
        return f'段落格式修复异常: {e}'


# =============================================================================
# P1: 建议型修复 — 节奏/情感/冲突薄弱
# 不直接改正文，通过 LLM 生成针对性改进建议写入 PMDecisionLog
# =============================================================================


async def _fix_rhythm_monotone(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """节奏单调改进建议 — LLM 分析章节节奏并给出改进方案。"""
    return await _generate_craft_suggestion(
        issue,
        project_id,
        user_id,
        db,
        dimension='节奏',
        prompt_template="""你是小说节奏分析专家。以下是第{ch}章的内容片段，节奏评分偏低。

【章节片段】
{content}

请给出节奏改进建议（3-5条）：
1. 哪些段落拖沓需要删减
2. 哪些地方应该加快节奏（缩短句子、增加动作）
3. 高潮部分是否需要前移或加强
4. 对话与描写的比例是否合适

格式：节奏建议：...""",
        breaker_name='rhythm_fix',
    )


async def _fix_emotion_flat(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """情感空洞改进建议 — LLM 分析情感表达并给出改进方案。"""
    return await _generate_craft_suggestion(
        issue,
        project_id,
        user_id,
        db,
        dimension='情感',
        prompt_template="""你是小说情感表达专家。以下是第{ch}章的内容片段，情感评分偏低。

【章节片段】
{content}

请给出情感改进建议（3-5条）：
1. 角色内心独白是否足够（缺少心理活动）
2. 关键情感场景的描写是否到位（需要更多细节）
3. 情感递进是否自然（是否有突兀转折）
4. 读者共鸣点是否设置（需要强化哪些情感锚点）

格式：情感建议：...""",
        breaker_name='emotion_fix',
    )


async def _fix_conflict_weak(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """冲突薄弱改进建议 — LLM 分析冲突设置并给出改进方案。"""
    return await _generate_craft_suggestion(
        issue,
        project_id,
        user_id,
        db,
        dimension='冲突',
        prompt_template="""你是小说冲突构建专家。以下是第{ch}章的内容片段，冲突强度偏低。

【章节片段】
{content}

请给出冲突改进建议（3-5条）：
1. 当前章节是否有核心冲突（缺少明确的对抗）
2. 冲突升级是否合理（是否需要增加障碍）
3. 角色间的矛盾是否被充分利用
4. 是否需要引入新的外部冲突或时间压力

格式：冲突建议：...""",
        breaker_name='conflict_fix',
    )


async def _generate_craft_suggestion(
    issue: dict[str, Any],
    project_id: str,
    user_id: str,
    db,
    dimension: str,
    prompt_template: str,
    breaker_name: str,
) -> str:
    """通用建议型修复 — 读取章节内容 + LLM 生成建议。

    建议型修复不改正文，验证时只检查建议是否非空。
    """
    from app.models.chapter import Chapter

    ch_num = issue.get('chapter_number', 0) or 0
    if not ch_num:
        return f'{dimension}改进建议跳过（无章节号）'

    # 读取章节内容
    ch_result = await db.execute(
        select(Chapter)
        .where(
            Chapter.project_id == project_id,
            Chapter.chapter_number == ch_num,
        )
        .limit(1)
    )
    chapter = ch_result.scalar_one_or_none()
    if not chapter or not chapter.content:
        return f'{dimension}改进建议跳过（章节内容不存在）'

    ch_content = (chapter.content or '')[:800]

    # LLM 生成建议
    if not is_pm_feature_enabled('optional.self_evolution'):
        return f'{dimension}改进建议未生成（LLM 功能未启用），建议人工审查第{ch_num}章的{dimension}问题'

    try:
        from app.services.pm.pm_ai_client import get_pm_ai_client
        from app.services.pm.pm_llm_guard import call_llm_with_guard

        ai_service = await get_pm_ai_client(user_id, db)
        if ai_service is None:
            return f'{dimension}改进建议跳过（用户未配置 API）'

        prompt = prompt_template.format(ch=ch_num, content=ch_content)
        from app.services.pm.pm_token_budget import BudgetContext

        result = await call_llm_with_guard(
            ai_service.generate_text,
            breaker_name=breaker_name,
            prompt=prompt,
            max_tokens=500,
            temperature=0.4,
            budget_ctx=BudgetContext(user_id=user_id, project_id=project_id, feature='repair', action=dimension, db=db),
        )
        if result:
            suggestion = (result.get('content') or '').strip()[:500]
            if suggestion:
                return f'{dimension}改进建议已生成（第{ch_num}章）\n{suggestion}'

        return f'{dimension}改进建议生成失败（LLM 返回为空）'
    except Exception as e:
        logger.warning(f'[PM-Agent] {dimension}建议生成失败: {e}')
        return f'{dimension}改进建议生成异常: {e}'


# =============================================================================
# P2: 大纲漂移修复 — LLM 生成大纲修正建议
# =============================================================================


async def _fix_outline_drift(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """大纲漂移修复 — LLM 分析大纲结构差异并生成修正建议。

    建议型修复：不直接修改大纲 structure，而是生成修正建议供用户在编辑器中采纳。
    """

    drifts = issue.get('drifts', [])
    if not drifts:
        return '大纲漂移修复跳过（无 drifts 信息）'

    # 读取相关章节的大纲信息
    from_ch = issue.get('from_chapter', 0) or 0
    to_ch = issue.get('to_chapter', 0) or 0

    drift_summary = '\n'.join(f'- {d}' for d in drifts[:5])

    if not is_pm_feature_enabled('optional.self_evolution'):
        return f'大纲漂移检测到（第{from_ch}→{to_ch}章），LLM 未启用，建议人工审查：\n{drift_summary}'

    try:
        from app.services.pm.pm_ai_client import get_pm_ai_client
        from app.services.pm.pm_llm_guard import call_llm_with_guard

        ai_service = await get_pm_ai_client(user_id, db)
        if ai_service is None:
            return f'大纲漂移检测到但用户未配置 API，建议人工审查：\n{drift_summary}'

        prompt = f"""你是小说大纲结构分析专家。以下是第{from_ch}章和第{to_ch}章之间检测到的大纲漂移问题。

【漂移问题】
{drift_summary}

请给出大纲修正建议（3-5条）：
1. 哪些结构变化偏离了原始大纲意图
2. 如何调整大纲使后续章节回归主线
3. 是否需要修改章节规划顺序或增删章节
4. 漂移是否带来了积极变化（有些漂移可能是剧情自然发展）

格式：大纲建议：..."""

        from app.services.pm.pm_token_budget import BudgetContext

        result = await call_llm_with_guard(
            ai_service.generate_text,
            breaker_name='outline_drift_fix',
            prompt=prompt,
            max_tokens=500,
            temperature=0.3,
            budget_ctx=BudgetContext(user_id=user_id, project_id=project_id, feature='repair', action='outline_drift', db=db),
        )
        if result:
            suggestion = (result.get('content') or '').strip()[:500]
            if suggestion:
                return f'大纲漂移修正建议已生成（第{from_ch}→{to_ch}章）\n{suggestion}'

        return f'大纲漂移修正建议生成失败（LLM 返回为空），建议人工审查：\n{drift_summary}'
    except Exception as e:
        logger.warning(f'[PM-Agent] 大纲漂移建议生成失败: {e}')
        return f'大纲漂移修正建议异常: {e}'


# =============================================================================
# P0.2: 漫剧 3 维修复（场景/分镜/对话）— 建议型
# 不直接改写用户创作正文，仅在目标分镜 ComicPanel.scene_metadata['pm_fix']
# 写入修复建议标记，并返回建议字符串供 PMDecisionLog.fix_details 记录。
# 签名统一为 _execute_fix 调用形式 (issue, project_id, user_id, db) -> str。
# =============================================================================


def _extract_panel_seqs(entities: list[str] | None) -> list[int]:
    """从 entities 提取全部 panel: 全局序号（保持顺序，跳过非法值）。"""
    if not entities:
        return []
    seqs = []
    for e in entities:
        if isinstance(e, str) and e.startswith('panel:'):
            try:
                seqs.append(int(e.split(':', 1)[1]))
            except ValueError:
                continue
    return seqs


async def _mark_panel_fix(
    db,
    project_id: str,
    seq: int,
    fix_type: str,
    suggestion: str,
) -> bool:
    """在 ComicPanel.scene_metadata['pm_fix'] 写入建议标记。

    返回是否写入成功（分镜不存在或 db 异常返回 False，不抛出）。
    """
    try:
        from app.models.comic import ComicPanel

        result = await db.execute(
            select(ComicPanel)
            .where(
                ComicPanel.project_id == project_id,
                ComicPanel.global_sequence == seq,
            )
            .limit(1)
        )
        panel = result.scalar_one_or_none()
        if panel is None:
            return False
        meta = dict(panel.scene_metadata or {})
        fixes = dict(meta.get('pm_fix') or {})
        fixes[fix_type] = {'suggestion': suggestion}
        meta['pm_fix'] = fixes
        panel.scene_metadata = meta
        await db.flush()
        return True
    except Exception as e:
        logger.warning('[PM-Agent] 写入分镜修复标记失败（非阻断）: %s', e)
        return False


async def _fix_scene_discontinuity(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """场景连续性修复建议 — 统一为前镜场景描述（建议型，不直接改写正文）。"""
    conflict_type = issue.get('conflict_type', 'time')
    scene_from = issue.get('scene_from', '')
    scene_to = issue.get('scene_to', '')
    page = issue.get('page', '?')
    seqs = _extract_panel_seqs(issue.get('entities'))
    if not seqs or not scene_from or not scene_to:
        return '场景连续性修复跳过（缺少场景描述或分镜序号）'
    target_seq = seqs[-1]  # 问题在后镜（当前描述异常一侧）
    suggestion = (
        f'建议将分镜 {target_seq} 的场景描述「{scene_to}」统一为前镜「{scene_from}」'
        f'（第{page}页，{conflict_type}冲突）'
    )
    written = await _mark_panel_fix(db, project_id, target_seq, 'scene_discontinuity', suggestion)
    tail = '，已写入分镜修复标记' if written else ''
    return f'场景连续性修复建议已生成（分镜 {seqs[0]}→{seqs[-1]}）{tail}: {suggestion}'


async def _fix_panel_transition(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """分镜衔接修复建议 — 建议替换中间分镜 camera_angle 打破单调节奏（建议型）。"""
    angle = issue.get('angle', '')
    count = issue.get('count', 0)
    seqs = _extract_panel_seqs(issue.get('entities'))
    if not seqs:
        return '分镜衔接修复跳过（缺少分镜序号）'
    start, end = seqs[0], seqs[-1]
    mid_seq = (start + end) // 2
    suggestion = (
        f'建议将分镜 {mid_seq} 的 camera_angle「{angle or "?"}」替换为其他景别，'
        f'打破连续 {count} 个相同角度的单调节奏'
    )
    written = await _mark_panel_fix(db, project_id, mid_seq, 'panel_transition', suggestion)
    tail = '，已写入分镜修复标记' if written else ''
    return f'分镜衔接修复建议已生成（分镜 {start}~{end}）{tail}: {suggestion}'


async def _fix_dialogue_inconsistency(issue: dict[str, Any], project_id: str, user_id: str, db) -> str:
    """对话语气统一建议 — 角色语气风格跳变，建议统一为前镜风格（建议型）。"""
    character = issue.get('character', '')
    style_from = issue.get('style_from', '')
    style_to = issue.get('style_to', '')
    seqs = _extract_panel_seqs(issue.get('entities'))
    if not seqs or not character:
        return '对话语气修复跳过（缺少角色或分镜序号）'
    target_seq = seqs[-1]
    suggestion = (
        f'建议将角色「{character}」在分镜 {target_seq} 的对话语气'
        f'由「{style_to}」统一为「{style_from}」'
    )
    written = await _mark_panel_fix(db, project_id, target_seq, 'dialogue_inconsistency', suggestion)
    tail = '，已写入分镜修复标记' if written else ''
    return f'对话语气统一建议已生成（角色「{character}」）{tail}: {suggestion}'
