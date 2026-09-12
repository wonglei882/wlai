"""
灵感模式·技能自生长系统

当 AI 遇到不会的问题时，自动生成 skill 来填补知识缺口。
后续同类问题直接命中已有 skill，无需重复"不知道"。

三层：
1. 缺口检测 — 识别 AI 回复中的"不知道"信号
2. 技能生成 — 自动创建 SKILL.md 格式的技能
3. 技能检索 — 对话前语义匹配已有技能
"""

from app.core import json_utils as json
from pathlib import Path
import asyncio
import os
from datetime import datetime, timezone
from sqlalchemy import select
import logging
from app.services.inspiration_sub.skill_system import InspirationSkillSystem

logger = logging.getLogger(__name__)

# =============================================================================
# 向量检索层（复用 memory_service 的 embedding model）
# =============================================================================
_mem_service = None


async def _search_skills_by_context(context: dict, db, user_id: str, threshold: float = 0.3) -> list:
    """
    按关键词/序列类型从 skill 文件中搜索经验教训，供生成约束使用。
    返回格式同 _deposit_quality_pattern_skill 写入的内容。
    """
    try:
        keyword = context.get('keyword', '')
        seq_index = context.get('seq_index', -1)

        # 关键序列类型映射
        seq_type_map = {
            0: '开头',
            1: '铺',
            2: '发展',
            3: '转折',
            4: '高潮',
            5: '中转',
            6: '破局',
            7: '解决',
        }
        seq_label = seq_type_map.get(seq_index, str(seq_index))

        # 搜索目录：global skill + 用户 skill
        hits = []
        dirs_to_search = []

        global_dir = os.path.join(InspirationSkillSystem.SKILLS_DIR, 'global')
        if os.path.isdir(global_dir):
            dirs_to_search.append(global_dir)

        user_skill_dir = InspirationSkillSystem._user_skills_dir(user_id)
        if os.path.isdir(user_skill_dir):
            dirs_to_search.append(user_skill_dir)

        search_terms = []
        if keyword:
            search_terms.append(keyword)
        search_terms.append(seq_label)
        search_terms.append('质量陷阱')
        search_terms.append('禁止')

        for search_dir in dirs_to_search:
            for fname in os.listdir(search_dir):
                if not fname.endswith('.md'):
                    continue
                fpath = os.path.join(search_dir, fname)
                try:
                    content = await asyncio.to_thread(Path(fpath).read_text, encoding='utf-8')
                except Exception:  # noqa: S112
                    continue

                # 关键词命中
                for term in search_terms:
                    if term and term in content[:500]:  # 只看前500字（摘要区）
                        skill_name = fname[:-3]
                        # 提取摘要（前200字）
                        summary = content[:200].replace('#', '').strip()
                        hits.append(
                            {
                                'name': skill_name,
                                'content': summary,
                                'score': 0.7,
                                'source': 'file',
                            }
                        )
                        break  # 一个文件只取一次

        # 按 score 排序去重
        seen = set()
        deduped = []
        for h in sorted(hits, key=lambda x: x['score'], reverse=True):
            if h['name'] not in seen:
                seen.add(h['name'])
                deduped.append(h)

        return deduped[:3]

    except Exception as e:
        logger.warning(f'[_search_skills_by_context] 搜索失败（非阻塞）: {e}')
        return []


# =============================================================================
# 方案1+2：诊断快速摘要（PM对话注入）+ 诊断持久化
# =============================================================================
async def _get_quick_diagnostic_summary(user_id: str, project_id: str, db) -> str:
    """30ms内返回诊断摘要（无问题返回空），用于PM对话system_prompt注入。

    只读关键指标，不做全量扫描：
      - 最近1条一致性状态（有内容才注）
      - 伏笔逾期数（有才注）
      - 未解决诊断日志（有才注）
    """
    from sqlalchemy import select, func
    from app.models.pm_diagnostic_log import PMDiagnosticLog
    from app.models.pm_consistency_state import PMConsistencyState
    from app.models.foreshadow import Foreshadow
    from app.models.chapter import Chapter

    parts = []

    # 1. 未解决的诊断日志（优先级最高）
    try:
        logs_r = await db.execute(
            select(PMDiagnosticLog)
            .where(
                PMDiagnosticLog.project_id == project_id,
                PMDiagnosticLog.resolved.is_(False),
            )
            .order_by(
                PMDiagnosticLog.severity.desc(),
                PMDiagnosticLog.created_at.desc(),
            )
            .limit(3)
        )
        unresolved = list(logs_r.scalars().all())
        if unresolved:
            sev_icon = {'critical': '🚨', 'warning': '⚠️'}
            for log in unresolved:
                icon = sev_icon.get(log.severity, '•')
                parts.append(f'{icon} 未解决诊断：{log.message[:60]}')
                if log.suggestion:
                    parts.append(f'  → {log.suggestion[:50]}')
    except Exception as e:
        logger.warning(f'[diagnostic] _get_quick_diagnostic_summary 失败: {e}')

    # 2. 最近一致性状态（有具体内容才注）
    try:
        cs_r = await db.execute(
            select(PMConsistencyState)
            .where(
                PMConsistencyState.project_id == project_id,
            )
            .order_by(PMConsistencyState.updated_at.desc())
            .limit(1)
        )
        cs = cs_r.scalar_one_or_none()
        if cs:
            issue = getattr(cs, 'issue_type', '') or getattr(cs, 'issue_summary', '')
            ch = getattr(cs, 'chapter_number', None)
            if issue and len(issue) > 3:
                parts.append(f'⚠️ 最近一致性问题：{issue}（第{ch}章）')
    except Exception as e:
        logger.warning(f'[_build_quick_diagnostic] 一致性状态扫描失败: {e}')

    # 3. 伏笔逾期数
    try:
        ch_r = await db.execute(select(func.max(Chapter.chapter_number)).where(Chapter.project_id == project_id))
        latest_ch = ch_r.scalar() or 0
        fs_r = await db.execute(
            select(Foreshadow).where(
                Foreshadow.project_id == project_id,
                Foreshadow.status.in_(['pending', 'planted']),
            )
        )
        overdue = []
        for f in fs_r.scalars().all():
            planted_ch = getattr(f, 'chapter_number', None) or 0
            if latest_ch - planted_ch >= 5:
                overdue.append(f.title)
        if overdue:
            parts.append(f'⚠️ 伏笔逾期：{len(overdue)}个（{"、".join(overdue[:3])}...）请优先处理')
    except Exception as e:
        logger.warning(f'[_build_quick_diagnostic] 伏笔逾期扫描失败: {e}')

    if not parts:
        return ''

    return '\n【PM诊断提醒】\n' + '\n'.join(parts) + '\n'


async def _upsert_diagnostic_log(
    db,
    project_id: str,
    user_id: str,
    diag_type: str,
    severity: str,
    message: str,
    suggestion: str = '',
    chapter_number: int = None,
    character_id: str = None,
) -> dict:
    """写入或更新诊断日志（每种类型只保留最新未解决的一条）。"""
    from app.models.pm_diagnostic_log import PMDiagnosticLog
    from sqlalchemy import select, update

    try:
        # 查是否已有未解决的同类诊断（1 小时内）
        from datetime import datetime, timedelta, timezone

        one_hour_ago = datetime.now(tz=timezone.utc) - timedelta(hours=1)

        existing_r = await db.execute(
            select(PMDiagnosticLog).where(
                PMDiagnosticLog.project_id == project_id,
                PMDiagnosticLog.diag_type == diag_type,
                PMDiagnosticLog.resolved.is_(False),
                PMDiagnosticLog.created_at >= one_hour_ago,  # 1 小时内
            )
        )
        existing = existing_r.scalar_one_or_none()

        if existing:
            stmt = (
                update(PMDiagnosticLog)
                .where(PMDiagnosticLog.id == existing.id)
                .values(
                    severity=severity,
                    message=message[:500],
                    suggestion=suggestion[:500] if suggestion else None,
                    chapter_number=chapter_number,
                    character_id=character_id,
                )
            )
            await db.execute(stmt)
            await db.commit()
            return {'action': 'updated', 'id': existing.id}
        else:
            log = PMDiagnosticLog(
                project_id=project_id,
                user_id=user_id,
                diag_type=diag_type,
                severity=severity,
                message=message[:500],
                suggestion=suggestion[:500] if suggestion else None,
                chapter_number=chapter_number,
                character_id=character_id,
            )
            db.add(log)
            await db.commit()
            return {'action': 'created', 'id': log.id}
    except Exception as e:
        return {'action': 'error', 'error': str(e)}


async def _resolve_diagnostic_log(db, diag_type: str, project_id: str, resolved_by: str = 'auto_fix') -> dict:
    """标记诊断日志为已解决（auto_fix成功后调用）。"""
    from app.models.pm_diagnostic_log import PMDiagnosticLog
    from sqlalchemy import update

    try:
        stmt = (
            update(PMDiagnosticLog)
            .where(
                PMDiagnosticLog.project_id == project_id,
                PMDiagnosticLog.diag_type == diag_type,
                PMDiagnosticLog.resolved.is_(False),
            )
            .values(
                resolved=True,
                resolved_at=datetime.now(tz=timezone.utc),
                resolved_by=resolved_by,
            )
        )
        result = await db.execute(stmt)
        await db.commit()
        return {'resolved': result.rowcount}
    except Exception as e:
        await db.rollback()
        return {'error': str(e)}


# =============================================================================
# L3.5 深扩：六大核心功能加强（伏笔追踪→冲突密度→大纲评分→一致性趋势→角色弧光→情感流向）
# =============================================================================


# -----------------------------------------------------------------------------
# 加强1：伏笔回收追踪
# -----------------------------------------------------------------------------
async def _track_foreshadow_recovery(db, project_id: str) -> list[dict]:
    """扫描伏笔回收状态。返回 [{title, age, status, urgency}, ...]"""
    try:
        from app.models.pm_consistency_state import PMConsistencyState

        stmt = (
            select(
                PMConsistencyState.chapter_number,
                PMConsistencyState.foreshadow_status,
            )
            .where(
                PMConsistencyState.project_id == project_id,
            )
            .order_by(PMConsistencyState.chapter_number)
        )
        rows = (await db.execute(stmt)).all()
        if not rows:
            return []

        # 构建伏笔种植记录
        planted: dict[str, int] = {}  # title -> chapter_number
        for row in rows:
            chapter_number, foreshadow_status = row[0], row[1]
            for title, status in (foreshadow_status or {}).items():
                if status == 'planted':
                    planted[title] = chapter_number
                elif status == 'recovered' and title in planted:
                    del planted[title]

        current_ch = rows[-1][0] if rows else 0
        results = []
        for title, planted_ch in planted.items():
            age = current_ch - planted_ch
            urgency = 'critical' if age >= 8 else 'warning' if age >= 5 else 'normal'
            results.append(
                {
                    'title': title,
                    'age': age,
                    'planted_chapter': planted_ch,
                    'current_chapter': current_ch,
                    'urgency': urgency,
                }
            )
        results.sort(key=lambda x: x['age'], reverse=True)
        return results
    except Exception as e:
        logger.warning(f'伏笔追踪失败: {e}')
        return []


# -----------------------------------------------------------------------------
# 加强2：冲突密度分析
# -----------------------------------------------------------------------------
async def _analyze_conflict_density(db, project_id: str) -> list[dict]:
    """统计每章冲突密度。返回 [{chapter, count, level, advice}, ...]"""
    try:
        from app.models.pm_consistency_state import PMConsistencyState

        stmt = (
            select(
                PMConsistencyState.chapter_number,
                PMConsistencyState.character_states,
            )
            .where(
                PMConsistencyState.project_id == project_id,
            )
            .order_by(PMConsistencyState.chapter_number.desc())
            .limit(10)
        )
        rows = (await db.execute(stmt)).all()
        rows.reverse()  # 从旧到新

        results = []
        for row in rows:
            chapter_number, character_states = row[0], row[1]
            count = 0
            for state in (character_states or {}).values():
                if '冲突' in str(state) or 'conflict' in str(state).lower():
                    count += 1
            level = 'healthy' if count >= 2 else 'low' if count == 1 else 'weak'
            advice = '' if level != 'weak' else '建议增加外部冲突'
            results.append(
                {
                    'chapter': chapter_number,
                    'count': count,
                    'level': level,
                    'advice': advice,
                }
            )
        return results
    except Exception as e:
        logger.warning(f'冲突密度分析失败: {e}')
        return []


# -----------------------------------------------------------------------------
# 加强3：大纲健康度评分
# -----------------------------------------------------------------------------
async def _score_outline_health(project_id: str, db=None) -> dict:
    """评分大纲健康度：主线清晰/卷间平衡/高潮分布/伏笔规划。"""
    try:
        from app.models.chapter import Chapter
        from app.models.outline import Outline
        from sqlalchemy import select

        if db is None:
            from app.database import get_engine

            engine = await get_engine(str(project_id)[:8] if project_id else 'default')
            async with engine.connect() as conn:
                # JOIN 获取大纲内容用于高潮检测
                stmt = (
                    select(Chapter, Outline.content)
                    .outerjoin(Outline, Chapter.outline_id == Outline.id)
                    .where(Chapter.project_id == project_id)
                    .order_by(Chapter.chapter_number)
                    .limit(200)
                )
                result = await conn.execute(stmt)
                chapters = [(row[0], row[1]) for row in result.all()]
            await engine.dispose()
        else:
            stmt = (
                select(Chapter, Outline.content)
                .outerjoin(Outline, Chapter.outline_id == Outline.id)
                .where(Chapter.project_id == project_id)
                .order_by(Chapter.chapter_number)
                .limit(200)
            )
            result = await db.execute(stmt)
            chapters = [(row[0], row[1]) for row in result.all()]

        if not chapters:
            return {'score': None, 'issues': [], 'suggestions': []}

        total = len(chapters)
        chapter_nums = [ch[0].chapter_number for ch in chapters if hasattr(ch[0], 'chapter_number')]
        issues, suggestions = [], []

        # 平衡性：章节数波动
        if chapter_nums:
            avg = sum(chapter_nums) / len(chapter_nums) if chapter_nums else 0
            if avg > 0:
                variance = sum((n - avg) ** 2 for n in chapter_nums) / len(chapter_nums)
                if variance > 50:
                    issues.append('卷间章节数波动较大，节奏可能失衡')
                    suggestions.append('建议各卷章节数控制在相近范围（±3章）')

        # 高潮分布：从关联的大纲内容提取 climax 关键词
        climax_count = sum(1 for ch, ol_content in chapters if ol_content and ('高潮' in str(ol_content) or '冲突' in str(ol_content)))
        if total > 0:
            expected = max(1, total // 5)
            if climax_count < expected:
                issues.append(f'高潮数量偏少（{climax_count}/{expected}推荐）')
                suggestions.append('建议每4-5章安排一个高潮节点')

        score = 10 - len(issues) * 2
        return {
            'score': max(5, score),
            'issues': issues,
            'suggestions': suggestions,
            'total_chapters': total,
        }
    except Exception as e:
        logger.warning(f'大纲健康度评分失败: {e}')
        return {'score': None, 'issues': [], 'suggestions': []}


# -----------------------------------------------------------------------------
# 加强4：一致性趋势分析
# -----------------------------------------------------------------------------
async def _analyze_consistency_trend(db, project_id: str) -> dict:
    """统计 auto_fix 调用趋势。返回 {direction, total, top_issues}。"""
    try:
        # 读取持久化的 _issue_counts（与 InspirationSkillSystem 共用同一技能目录）
        skill_dir = InspirationSkillSystem.SKILLS_DIR
        counts_file = os.path.join(skill_dir, '_review_counts.json')
        counts = {}
        if os.path.exists(counts_file):
            counts = json.loads(await asyncio.to_thread(Path(counts_file).read_text, encoding='utf-8'))

        if not counts:
            return {'direction': 'stable', 'total': 0, 'top_issues': []}

        total = sum(counts.values())
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:3]
        top_issues = [{'type': k, 'count': v} for k, v in top]

        direction = 'stable'
        if total > 20:
            direction = 'worsening'
        elif total < 5:
            direction = 'improving'

        return {'direction': direction, 'total': total, 'top_issues': top_issues}
    except Exception as e:
        logger.warning(f'一致性趋势分析失败: {e}')
        return {'direction': 'stable', 'total': 0, 'top_issues': []}


# -----------------------------------------------------------------------------
# 加强5：角色弧光追踪
# -----------------------------------------------------------------------------
async def _track_character_arc(db, project_id: str) -> list[dict]:
    """追踪角色成长轨迹。返回 [{name, states: [(ch, state)], arc_score}, ...]"""
    try:
        from app.models.pm_consistency_state import PMConsistencyState

        stmt = (
            select(
                PMConsistencyState.chapter_number,
                PMConsistencyState.character_states,
            )
            .where(
                PMConsistencyState.project_id == project_id,
            )
            .order_by(PMConsistencyState.chapter_number)
        )
        rows = (await db.execute(stmt)).all()
        if len(rows) < 3:
            return []

        # 收集所有角色
        all_chars: dict[str, list] = {}
        for row in rows:
            chapter_number, character_states = row[0], row[1]
            for name, state in (character_states or {}).items():
                all_chars.setdefault(name, []).append((chapter_number, state))

        arcs = []
        for name, states in all_chars.items():
            if len(states) < 2:
                continue
            # 计算弧光分：状态变化次数 / 总章数
            changes = sum(
                1
                for i in range(1, len(states))
                if states[i][1].get('emotion') != states[i - 1][1].get('emotion') or states[i][1].get('location') != states[i - 1][1].get('location')
            )
            arc_score = min(10, int(changes / len(states) * 10 + 5))
            arcs.append(
                {
                    'name': name,
                    'states': states[-3:],  # 最近3个状态
                    'arc_score': arc_score,
                    'change_count': changes,
                    'status': 'healthy' if arc_score >= 6 else 'flat' if arc_score >= 4 else 'weak',
                }
            )
        arcs.sort(key=lambda x: x['arc_score'], reverse=True)
        return arcs[:5]
    except Exception as e:
        logger.warning(f'角色弧光追踪失败: {e}')
        return []


# -----------------------------------------------------------------------------
# 加强6：章节情感流向
# -----------------------------------------------------------------------------
_EMOTION_TAGS = {
    '紧张': 'tension',
    '平静': 'calm',
    '愤怒': 'anger',
    '悲伤': 'sad',
    '喜悦': 'joy',
    '恐惧': 'fear',
    '期待': 'anticipation',
    '温暖': 'warmth',
    '压抑': 'depression',
}


async def _analyze_emotion_flow(db, project_id: str) -> dict:
    """从最近章节提取情感标签，绘制情感曲线。"""
    try:
        from app.models.pm_consistency_state import PMConsistencyState

        stmt = (
            select(
                PMConsistencyState.chapter_number,
                PMConsistencyState.character_states,
            )
            .where(
                PMConsistencyState.project_id == project_id,
            )
            .order_by(PMConsistencyState.chapter_number.desc())
            .limit(8)
        )
        rows = list((await db.execute(stmt)).all())
        rows.reverse()

        if len(rows) < 3:
            return {'flow': [], 'flat_warning': None}

        flow = []
        for row in rows:
            chapter_number, character_states = row[0], row[1]
            primary = '平静'
            for state in (character_states or {}).values():
                state_str = str(state)
                for tag, _eng in _EMOTION_TAGS.items():
                    if tag in state_str:
                        primary = tag
                        break
                if primary != '平静':
                    break
            flow.append({'chapter': chapter_number, 'emotion': primary})

        # 检测单调段
        flat_warning = None
        for i in range(len(flow) - 2):
            if all(flow[i]['emotion'] == f['emotion'] for f in flow[i : i + 3]):
                flat_warning = f'连续{3}章情感「{flow[i]["emotion"]}」，节奏偏平，建议加入情感反转'
                break

        return {'flow': flow, 'flat_warning': flat_warning}
    except Exception as e:
        logger.warning(f'情感流向分析失败: {e}')
        return {'flow': [], 'flat_warning': None}


# -----------------------------------------------------------------------------
# 统一诊断报告生成（带缓存：TTL=10分钟）
# -----------------------------------------------------------------------------
_DIAGNOSTIC_CACHE_TTL = 600  # 10分钟


async def _get_cached_diagnostic(db, project_id: str) -> tuple[str, bool]:
    """从 PMSessionState.extra_data 读取诊断缓存，返回(text, is_valid)。"""
    try:
        from app.models.pm_session_state import PMSessionState
        from sqlalchemy import select

        stmt = select(PMSessionState).where(PMSessionState.project_id == project_id).order_by(PMSessionState.updated_at.desc()).limit(1)
        result = await db.execute(stmt)
        state = result.scalar_one_or_none()
        if state and state.extra_data:
            cached = state.extra_data.get('_cached_diagnostic')
            if cached:
                import time

                if time.time() - cached.get('_cached_at', 0) < _DIAGNOSTIC_CACHE_TTL:
                    return cached.get('_diagnostic_text', ''), True
    except Exception as e:
        logger.warning(f'[diagnostic] _get_cached_diagnostic 失败: {e}')
    return '', False


async def _set_cached_diagnostic(db, project_id: str, text: str) -> None:
    """将诊断报告写入 PMSessionState.extra_data 缓存。"""
    try:
        from app.models.pm_session_state import PMSessionState
        from sqlalchemy import select
        import time

        stmt = select(PMSessionState).where(PMSessionState.project_id == project_id).order_by(PMSessionState.updated_at.desc()).limit(1)
        result = await db.execute(stmt)
        state = result.scalar_one_or_none()
        if state:
            extra = dict(state.extra_data or {})
            extra['_cached_diagnostic'] = {
                '_diagnostic_text': text,
                '_cached_at': time.time(),
            }
            state.extra_data = extra
        await db.commit()
    except Exception as e:
        logger.warning(f'诊断缓存写入失败: {e}')


async def _run_full_diagnostic(db, project_id: str) -> str:
    """运行六大分析，生成统一的诊断报告。无声问题时返回空字符串。TTL缓存10分钟。"""
    # 缓存命中检测
    cached_text, is_valid = await _get_cached_diagnostic(db, project_id)
    if is_valid and cached_text:
        logger.info(f'[诊断缓存] 命中，project={project_id[:8]}')
        return cached_text

    # 实际运行六大诊断
    from app.models.project import Project

    proj_r = await db.execute(select(Project).where(Project.id == project_id))
    proj = proj_r.scalar_one_or_none()
    user_id = str(proj.user_id) if proj else 'system'

    parts = []

    # 伏笔回收（必须最前：最影响阅读体验）
    foreshadows = await _track_foreshadow_recovery(db, project_id)
    critical = [f for f in foreshadows if f['urgency'] == 'critical']
    warning = [f for f in foreshadows if f['urgency'] == 'warning']
    if critical:
        parts.append(f'🚨 伏笔回收（已植入{critical[0]["age"]}章+）：')
        for f in critical[:3]:
            parts.append(f'  • 「{f["title"]}」已植入{f["age"]}章，建议立即回收')
        titles = '、'.join([f['title'] for f in critical[:3]])
        await _upsert_diagnostic_log(
            db,
            project_id,
            user_id,
            'foreshadow_overdue',
            'critical',
            f'伏笔逾期严重{len(critical)}个',
            f'优先回收：{titles}',
        )
    if warning:
        parts.append('⚠️ 伏笔回收（待处理）：')
        for f in warning[:3]:
            parts.append(f'  • 「{f["title"]}」已植入{f["age"]}章')
        titles = '、'.join([f['title'] for f in warning[:3]])
        await _upsert_diagnostic_log(db, project_id, user_id, 'foreshadow_overdue', 'warning', f'伏笔逾期{len(warning)}个', f'关注：{titles}')

    # 冲突密度
    conflicts = await _analyze_conflict_density(db, project_id)
    weak = [c for c in conflicts if c['level'] in ('weak', 'low')]
    if weak:
        ch_nums = '、'.join([f'第{c["chapter"]}章' for c in weak[:3]])
        parts.append('⚔️ 冲突薄弱章节：')
        for c in weak[:3]:
            parts.append(f'  • 第{c["chapter"]}章（{c["count"]}个冲突）{c["advice"]}')
        await _upsert_diagnostic_log(db, project_id, user_id, 'conflict_dense', 'warning', f'冲突薄弱章节{len(weak)}个', f'建议加强：{ch_nums}')

    # 大纲健康度
    outline = await _score_outline_health(project_id, db)
    if outline.get('score') is not None:
        score = outline['score']
        icon = '✅' if score >= 8 else '⚠️' if score >= 6 else '🚨'
        parts.append(f'{icon} 大纲健康度：{score}/10')
        for iss in outline.get('issues', [])[:2]:
            parts.append(f'  • {iss}')
        for sug in outline.get('suggestions', [])[:2]:
            parts.append(f'  💡 {sug}')
        severity = 'warning' if score >= 6 else 'critical'
        issues_str = '、'.join(outline.get('issues', [])[:2])
        await _upsert_diagnostic_log(db, project_id, user_id, 'outline_health', severity, f'大纲健康度{score}/10', issues_str)

    # 一致性趋势
    trend = await _analyze_consistency_trend(db, project_id)
    if trend.get('total', 0) > 0:
        dir_icon = {'improving': '📉', 'worsening': '📈', 'stable': '➡️'}.get(trend['direction'], '➡️')
        parts.append(f'{dir_icon} 一致性趋势：近端修复{trend["total"]}次（{trend["direction"]}）')
        for iss in trend.get('top_issues', [])[:2]:
            parts.append(f'  • {iss["type"]}：{iss["count"]}次')
        if trend['direction'] == 'worsening':
            top_issue = trend.get('top_issues', [{}])[0].get('type', '一致性问题')
            await _upsert_diagnostic_log(
                db,
                project_id,
                user_id,
                'consistency_issue',
                'warning',
                f'一致性趋势{trend["direction"]}（{trend["total"]}次修复）',
                top_issue,
            )

    # 角色弧光
    arcs = await _track_character_arc(db, project_id)
    weak_arcs = [a for a in arcs if a['status'] in ('weak', 'flat')]
    if weak_arcs:
        parts.append('📈 角色弧光（需关注）：')
        for a in weak_arcs[:2]:
            parts.append(f'  • 「{a["name"]}」弧光{a["arc_score"]}/10（状态变化{a["change_count"]}次），{a["status"]}')
        parts.append('  💡 建议增加角色内心转折事件')
        names = '、'.join([a['name'] for a in weak_arcs[:2]])
        await _upsert_diagnostic_log(db, project_id, user_id, 'arc_incomplete', 'warning', f'角色弧光薄弱：{names}', '建议增加内心转折事件')

    # 情感流向
    emotion = await _analyze_emotion_flow(db, project_id)
    if emotion.get('flat_warning'):
        parts.append(f'📉 情感单调预警：{emotion["flat_warning"]}')
        await _upsert_diagnostic_log(
            db,
            project_id,
            user_id,
            'style_drift',
            'warning',
            f'情感单调：{emotion["flat_warning"]}',
            '建议增加情感反转',
        )

    if parts:
        text = '\n🔍 【项目诊断报告】\n' + '\n'.join(parts)
        await _set_cached_diagnostic(db, project_id, text)
        return text
    return ''


# =============================================================================
# L3.5 深4：主动发现问题（升级为六大诊断）
# =============================================================================


_PROACTIVE_SCAN_TOOLS = {
    'pm_auto_fix_character_state': 'scan_character_jumps',
    'pm_create_foreshadow': 'scan_unresolved_foreshadows',
    'pm_update_body': 'scan_rhythm_anomalies',
}
