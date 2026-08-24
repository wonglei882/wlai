"""PM 写操作工具集 — 诊断增强操作（第4批）

由 pm_write_operations.py 拆分而来（god file 专项重构）。
"""

from app.agent.domain.tools.pm_write_base import logger


async def pm_diagnose_project(project_id: str, db, user_id: str = '') -> dict:
    """整合所有已有分析服务，生成完整项目诊断报告。

    调用链：
      LongNovelGuardian.scan()  → 伏笔/角色/时间线/主线问题
      analyze_writing_style()   → 近3章文风一致性
      detect_progress_trend()   → 章节质量趋势
      StructureNode             → POV分布/节拍进度
      CharacterRelationship     → 关系网摘要
    """
    from app.services.guardian.long_novel_guardian import LongNovelGuardian
    from app.models.character import Character
    from app.models.foreshadow import Foreshadow
    from app.models.project import Project
    from app.models.story_line import StoryLine
    from app.models.chapter import Chapter
    from app.models.narrative_structure import StructureNode
    from app.agent.infrastructure.text_analysis import analyze_writing_style
    from app.agent.infrastructure.progress_analyzer import detect_progress_trend
    from app.services.inspiration_sub.diagnostic import _upsert_diagnostic_log
    from sqlalchemy import select, func

    lines = []
    issues = []

    # 1. LongNovelGuardian 综合扫描
    try:
        proj_r = await db.execute(select(Project).where(Project.id == project_id))
        project = proj_r.scalar_one_or_none()
        if not project:
            return {'success': False, 'message': '项目不存在'}

        ch_r = await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number))
        chapters = list(ch_r.scalars().all())

        char_r = await db.execute(select(Character).where(Character.project_id == project_id))
        characters = list(char_r.scalars().all())

        fore_r = await db.execute(select(Foreshadow).where(Foreshadow.project_id == project_id))
        foreshadows = list(fore_r.scalars().all())

        sl_r = await db.execute(select(StoryLine).where(StoryLine.project_id == project_id))
        storylines = list(sl_r.scalars().all())

        guardian = LongNovelGuardian()
        report = await guardian.scan(project, chapters, characters, foreshadows, storylines)
        total = report.total()
        critical = report.critical_count()
        high = report.high_count()

        lines.append(f'📋 综合健康检查：{total}个问题（严重{critical}个，高危{high}个）')
        for iss in (report.issues or [])[:8]:
            sev_icon = {'critical': '🚨', 'high': '⚠️', 'medium': '🔔', 'low': '💡'}.get(iss.severity, '•')
            lines.append(f'  {sev_icon} [{iss.severity.upper()}] {iss.msg[:80]}')
            if iss.suggestion:
                issues.append(f'  → {iss.suggestion[:60]}')
    except Exception as e:
        lines.append(f'⚠️ 健康检查异常: {e}')

    # 2. 文风一致性（近3章）
    try:
        style_reports = []
        for ch in chapters[-3:]:
            if ch.content:
                s = analyze_writing_style(ch.content)
                style_reports.append(s)
        if style_reports:
            avg_dialog = sum(s.get('dialogue_ratio', 0) for s in style_reports) / len(style_reports)
            avg_emotion = sum(s.get('emotion_word_count', 0) for s in style_reports)
            lines.append(f'✍️ 近3章文风：对话占比{avg_dialog * 100:.0f}%，情感词{avg_emotion}个')
    except Exception as e:
        lines.append(f'⚠️ 文风分析异常: {e}')

    # 3. 质量趋势（从 expansion_plan 提取分数）
    try:
        scores = []
        for ch in chapters:
            if ch.expansion_plan:
                import json

                ep = json.loads(ch.expansion_plan)
                score = ep.get('quality_score') or ep.get('pacing_score')
                if score:
                    scores.append(float(score))
        if len(scores) >= 3:
            trend = detect_progress_trend(scores[-10:])
            icon = {'上升': '📈', '下降': '📉', '平稳': '➡️'}.get(trend.get('trend', ''), '➡️')
            lines.append(f'{icon} 质量趋势：{trend.get("trend", "未知")}（置信度{trend.get("confidence", 0) * 100:.0f}%）')
            if trend.get('advice'):
                lines.append(f'  → {trend["advice"]}')
    except Exception as e:
        logger.warning(f'[pm_diagnose_project] 质量趋势扫描失败: {e}')

    # 方案4延伸：主线健康度检查（LongNovelGuardian._check_main_plot）
    try:
        from app.services.guardian.long_novel_guardian import LongNovelGuardian

        guardian = LongNovelGuardian()

        # 查 storylines 和 chapters（用于主线检查）
        from app.models.story_line import StoryLine
        from app.models.chapter import Chapter

        sl_r = await db.execute(select(StoryLine).where(StoryLine.project_id == project_id))
        storylines = list(sl_r.scalars().all())
        ch_r = await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number.desc()).limit(20))
        recent_chapters = list(ch_r.scalars().all())

        if not storylines:
            lines.append('✅ 主线健康：暂无支线规划')
        else:
            main_issues = guardian._check_main_plot(
                storylines=[
                    {
                        'id': s.id,
                        'name': s.name,
                        'status': s.status,
                        'description': getattr(s, 'description', None),
                        'line_type': getattr(s, 'line_type', 'sub'),
                    }
                    for s in storylines
                ],
                chapters=[{'chapter_number': c.chapter_number, 'content': c.content} for c in recent_chapters],
                latest_n=5,
            )
            if main_issues:
                lines.append(f'🎯 主线健康（问题{len(main_issues)}个）：')
                for iss in main_issues[:3]:
                    lines.append(f'  • {iss.get("description", str(iss))}')
                await _upsert_diagnostic_log(
                    db,
                    project_id,
                    user_id,
                    'main_plot_drift',
                    'warning',
                    f'主线健康问题{len(main_issues)}个',
                    '、'.join([iss.get('description', '') for iss in main_issues[:2]]),
                )
            else:
                lines.append('✅ 主线健康：推进正常')
    except Exception as mp_err:
        logger.warning(f'[pm_diagnose_project] 主线检查失败: {mp_err}')

    # 4. POV 分布 + 合理性判断（方案4）
    try:
        pov_stmt = (
            select(StructureNode.pov_character_id, func.count(StructureNode.id).label('count'))
            .where(StructureNode.project_id == project_id, StructureNode.pov_character_id.isnot(None))
            .group_by(StructureNode.pov_character_id)
        )
        pov_r = await db.execute(pov_stmt)
        pov_rows = list(pov_r.all())
        if pov_rows:
            char_name_map = {c.id: c.name for c in characters}
            pov_lines = [f'{char_name_map.get(pid, pid[:8])}×{cnt}章' for pid, cnt in pov_rows[:5]]
            lines.append(f'👁️ POV分布：{", ".join(pov_lines)}')

            # 方案4：POV合理性判断
            total_nodes = sum(cnt for _, cnt in pov_rows)
            protagonist_nodes = next(
                (cnt for pid, cnt in pov_rows if char_name_map.get(pid) in [c.name for c in characters if c.role_type == 'protagonist']),
                0,
            )
            if protagonist_nodes == 0 and len(chapters) >= 3:
                lines.append('  ⚠️ 主角连续3章以上无POV，读者疲劳风险高')
            elif total_nodes > 0 and protagonist_nodes / total_nodes < 0.3:
                lines.append('  ⚠️ 主角POV占比过低（<30%），建议增加主角视角章节')
        else:
            lines.append('👁️ POV分布：未设置（建议在大纲结构中标注每章视角）')
    except Exception as e:
        logger.warning(f'[pm_diagnose_project] POV分布扫描失败: {e}')

    # 5. 节拍/结构节点进度
    try:
        node_stmt = select(func.count(StructureNode.id)).where(StructureNode.project_id == project_id)
        node_r = await db.execute(node_stmt)
        node_count = node_r.scalar() or 0
        total_ch = len(chapters)
        lines.append(f'🎬 结构节点：{node_count}个（章节{total_ch}章）')
        if node_count > 0 and total_ch > 0:
            ratio = node_count / total_ch
            if ratio < 0.5:
                lines.append('  ⚠️ 结构节点偏少，建议增加节点以细化节拍')
    except Exception as e:
        logger.warning(f'[pm_diagnose_project] 结构节点扫描失败: {e}')

    # 方案4：角色弧光完整性判断
    try:
        from app.models.pm_consistency_state import PMConsistencyState

        arc_stmt = (
            select(PMConsistencyState.character_name, func.count(PMConsistencyState.id).label('state_changes'))
            .where(
                PMConsistencyState.project_id == project_id,
                PMConsistencyState.character_name.isnot(None),
            )
            .group_by(PMConsistencyState.character_name)
        )
        arc_r = await db.execute(arc_stmt)
        arc_rows = list(arc_r.all())
        if arc_rows and len(chapters) > 0:
            arc_map = {name: changes for name, changes in arc_rows}
            for char in characters:
                if char.role_type == 'protagonist':
                    changes = arc_map.get(char.name, 0)
                    arc_score = min(10, changes / max(1, len(chapters)) * 10)
                    if arc_score < 2:
                        lines.append(f'📈 角色「{char.name}」弧光薄弱（变化{changes}次/{len(chapters)}章），缺少成长弧线')
                    elif arc_score > 5 and changes >= 3:
                        lines.append(f'✅ 角色「{char.name}」弧光健康（变化{changes}次）')
    except Exception as e:
        logger.warning(f'[pm_diagnose_project] 角色弧光扫描失败: {e}')

    # 6. 关系网摘要
    try:
        from app.models.relationship import CharacterRelationship

        rel_stmt = select(func.count(CharacterRelationship.id)).where(CharacterRelationship.project_id == project_id)
        rel_r = await db.execute(rel_stmt)
        rel_count = rel_r.scalar() or 0
        char_count = len(characters)
        lines.append(f'👥 关系网：{char_count}个角色，{rel_count}条关系')
        if char_count > 0 and rel_count == 0:
            lines.append('  ⚠️ 尚未建立角色关系，建议补充')
    except Exception as e:
        logger.warning(f'[pm_diagnose_project] 关系网扫描失败: {e}')

    if issues:
        lines.append('')
        lines.append('💡 优先修复建议：')
        for iss in issues[:5]:
            lines.append(iss)

    return {
        'success': True,
        'message': '\n'.join(lines),
        'data': {'lines': lines, 'issue_count': len(issues)},
    }


async def pm_analyze_relationships(project_id: str, db) -> dict:
    """分析角色关系网：生成关系图谱摘要+断线预警+冲突建议。"""
    from app.models.character import Character
    from app.models.relationship import CharacterRelationship
    from sqlalchemy import select

    char_r = await db.execute(select(Character).where(Character.project_id == project_id))
    characters = {c.id: c for c in char_r.scalars().all()}

    rel_r = await db.execute(select(CharacterRelationship).where(CharacterRelationship.project_id == project_id))
    relationships = list(rel_r.scalars().all())

    if not characters:
        return {'success': False, 'message': '项目中没有角色'}

    lines = [f'👥 角色关系网分析（{len(characters)}个角色，{len(relationships)}条关系）']
    lines.append('')

    # 按关系类型分组
    hostile, friendly, neutral = [], [], []
    for rel in relationships:
        c_a = characters.get(rel.character_from_id)
        c_b = characters.get(rel.character_to_id)
        if not c_a or not c_b:
            continue
        name_a, name_b = c_a.name, c_b.name
        rel_name = rel.relationship_name or '未知关系'
        intimacy = rel.intimacy_level or 50

        entry = f'  {name_a} —[{rel_name}×{intimacy}]—> {name_b}'
        if rel_name in ('敌对', '仇恨', '对立'):
            hostile.append(entry)
        elif intimacy > 60:
            friendly.append(entry)
        else:
            neutral.append(entry)

    if hostile:
        lines.append('⚔️ 敌对关系：')
        lines.extend(hostile)
        lines.append('')
    if friendly:
        lines.append('🤝 友好关系：')
        lines.extend(friendly)
        lines.append('')
    if neutral:
        lines.append('💬 一般关系：')
        lines.extend(neutral[:5])
        if len(neutral) > 5:
            lines.append(f'  ...还有{len(neutral) - 5}条')

    # 断线预警：主角有对话但没有关系定义的角色
    lines.append('')
    lines.append('⚠️ 断线预警：')
    char_ids_with_rels = set()
    for rel in relationships:
        char_ids_with_rels.add(rel.character_from_id)
        char_ids_with_rels.add(rel.character_to_id)

    lonely = [c.name for c in characters.values() if c.role_type in ('protagonist', 'supporting') and c.id not in char_ids_with_rels]
    if lonely:
        lines.append(f'  主角/重要配角未建立任何关系：{", ".join(lonely)}')
        lines.append('  → 建议为主角建立至少1条核心关系')
    else:
        lines.append('  ✅ 所有重要角色均已建立关系')

    # 潜在冲突建议
    protagonist = next((c for c in characters.values() if c.role_type == 'protagonist'), None)
    if protagonist and friendly:
        lines.append('')
        lines.append('💡 冲突设计建议：')
        for rel in relationships:
            if rel.intimacy_level and rel.intimacy_level > 70:
                c_a = characters.get(rel.character_from_id)
                c_b = characters.get(rel.character_to_id)
                if c_a and c_b:
                    lines.append(f'  • {c_a.name}与{c_b.name}关系亲密，可设计「信任破裂」类冲突增加张力')

    return {
        'success': True,
        'message': '\n'.join(lines),
        'data': {
            'char_count': len(characters),
            'rel_count': len(relationships),
            'hostile_count': len(hostile),
            'friendly_count': len(friendly),
        },
    }
