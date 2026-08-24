"""PM 一致性守护者 — 状态快照提取 + 跨章一致性检查 + 警报"""

import contextlib
import math
from collections import Counter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.logger import get_logger
from app.models.pm_consistency_state import PMConsistencyState
from app.models.chapter import Chapter
from app.models.project import Project
from app.models.character import Character
from app.models.foreshadow import Foreshadow
from app.services.pm.pm_guardian_models import ConsistencyIssue, ConsistencyCheckResult
from app.services.pm.pm_guardian_health import full_health_check as _full_health_check
from app.services.pm.scan_support import filter_names_by_whitelist


def _cosine_similarity(v1: dict, v2: dict) -> float:
    """P3-1 简化 TF-IDF：余弦相似度（无 sklearn）。"""
    if not v1 or not v2:
        return 0.0

    # 所有词汇
    vocab = set(v1.keys()) | set(v2.keys())

    # 向量点积
    dot = sum(v1.get(w, 0) * v2.get(w, 0) for w in vocab)

    # 向量模
    norm1 = math.sqrt(sum(v**2 for v in v1.values()))
    norm2 = math.sqrt(sum(v**2 for v in v2.values()))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot / (norm1 * norm2)


def _text_to_tfidf(text: str, idf_weights: dict | None = None) -> dict:
    """文本转 TF-IDF 向量（简化版，无预训练 IDF）。"""
    import re as _re

    # 提取 2-6 字中文词组
    words = _re.findall(r'[\u4e00-\u9fff]{2,6}', text[:1000])
    if not words:
        return {}

    # TF
    tf = Counter(words)
    total = len(words)
    tf_normalized = {w: c / total for w, c in tf.items()}

    # 如果有 IDF 权重（预训练），乘上去；否则只用 TF
    if idf_weights:
        return {w: tf_normalized[w] * idf_weights.get(w, 1.0) for w in tf_normalized}

    return tf_normalized


logger = get_logger(__name__)


# ============ 守护者服务 ============


class PMConsistencyGuardian:
    """PM 一致性守护者

    职责：
    1. 章节生成后自动提取状态快照（Layer 1 数据写入）
    2. 章节生成前做一致性检查（Layer 2 事件触发）
    3. 提供三个 PM 工具的底层实现（Layer 3 能力层）
    """

    def __init__(self, project_id: str, db: AsyncSession, chapter_number: int | None = None):
        self.project_id = project_id
        self.db = db
        self.chapter_number = chapter_number

    # ==================== P1: 状态提取 ====================

    async def extract_and_save(
        self,
        chapter: Chapter,
        analysis_result: dict | None = None,
    ) -> PMConsistencyState:
        """章节生成/分析完成后，提取状态并写入快照表

        Args:
            chapter: 刚生成/分析完的章节
            analysis_result: PlotAnalyzer 返回的分析结果（含 character_states / foreshadows 等）
        """
        # P0 修复：入口防御性 rollback，防止调用方遗留 aborted 事务状态
        # 导致后续所有 DB 操作报 InFailedSQLTransactionError（数据中 162 次该异常的根因）
        with contextlib.suppress(Exception):
            await self.db.rollback()

        # rollback 会 expire session 内全部 ORM 对象；此后同步访问 chapter 属性
        # 会触发隐式 lazy refresh 并抛 MissingGreenlet（asyncio 下禁止隐式同步 IO）。
        # 显式异步刷新，恢复传入对象的属性可用性。
        await self.db.refresh(chapter)

        ch_number = chapter.chapter_number

        # 读取已有快照（如果有则覆盖）
        existing_r = await self.db.execute(
            select(PMConsistencyState).where(
                PMConsistencyState.project_id == self.project_id,
                PMConsistencyState.chapter_number == ch_number,
            )
        )
        existing = existing_r.scalar_one_or_none()

        # === 提取角色状态 ===
        character_states = {}
        ai_char_states_found = False

        if analysis_result and analysis_result.get('character_states'):
            for cs in analysis_result['character_states']:
                if isinstance(cs, dict):
                    name = cs.get('character_name', '') or cs.get('name', '') or cs.get('character', '')
                    if name:
                        ai_char_states_found = True
                        character_states[name] = {
                            # 兼容两种字段名：PlotAnalyzer 输出 new_location/location 均有出现
                            'location': cs.get('new_location', '') or cs.get('location', '') or '',
                            'emotion': cs.get('state_after', '') or cs.get('psychological_change', ''),
                            'status': cs.get('survival_status', '') or cs.get('state_after', '') or 'active',
                            'goal': cs.get('key_event', ''),
                            'relationship_changes': cs.get('relationship_changes', {}),
                        }

        if not ai_char_states_found:
            # 兜底：从角色表读当前状态（AI 未输出角色状态或字段映射无匹配）
            char_r = await self.db.execute(select(Character).where(Character.project_id == self.project_id))
            for c in char_r.scalars().all():
                character_states[c.name] = {
                    'location': '',
                    'emotion': c.current_state or '',
                    'status': c.status or 'active',
                    'goal': '',
                    'relationship_changes': {},
                }
            if analysis_result and analysis_result.get('character_states'):
                logger.warning(
                    f'⚠️ 角色状态字段映射无匹配: project={self.project_id[:8]} ch={ch_number} '
                    f'AI返回{len(analysis_result.get("character_states", []))}条但提取0条，已降级到角色表'
                )

        # === 提取伏笔状态 ===
        foreshadow_status = {}
        foreshadow_r = await self.db.execute(select(Foreshadow).where(Foreshadow.project_id == self.project_id))
        for f in foreshadow_r.scalars().all():
            foreshadow_status[f.title or f.id[:8]] = f.status

        # === 提取角色弧线进度（从 character_state_history 推断）===
        arc_progress = {}
        char_r = await self.db.execute(select(Character).where(Character.project_id == self.project_id))
        for c in char_r.scalars().all():
            if c.role_type:
                stage = f'{c.role_type}_ch{c.main_career_stage or 1}' if c.main_career_stage else c.role_type
                arc_progress[c.name] = stage

        # === 世界观进程（从 Project.world_rules 和前几章推断）===
        # 修复：原逻辑 md5(Project.world_rules[:200]) 是项目级字段，
        # 不改 world_rules 所有章节 hash 永远相同，检测的是"设定被改"而非"章节漂移"。
        # 改为章节级：提取 world_rules 中的关键概念，只 hash "本章实际出现的规则子集"，
        # 相邻章节命中规则差异 > 50% 才算漂移。
        world_states = {}
        proj_r = await self.db.execute(select(Project).where(Project.id == self.project_id))
        proj = proj_r.scalar_one_or_none()
        if proj and proj.world_rules:
            import hashlib
            import re as _re

            rules_text = proj.world_rules or ''
            # 提取 world_rules 中的关键概念（2-6 字中文词组）
            rule_keywords = set(_re.findall(r'[\u4e00-\u9fff]{2,6}', rules_text[:1000]))

            chapter_content = chapter.content or ''
            # 本章正文中实际出现的规则关键词
            appeared = sorted(k for k in rule_keywords if k in chapter_content)

            # P3-1 TF-IDF 余弦相似度（替代纯 hash）
            # 保留 hash 兼容旧逻辑，新增 tfidf 向量
            world_states['_world_rules_hash'] = (
                hashlib.md5('|'.join(appeared).encode('utf-8'), usedforsecurity=False).hexdigest()[:16] if appeared else 'empty'
            )
            world_states['_appeared_rules'] = appeared[:20]
            # 章节 TF-IDF 向量（用于余弦相似度）
            world_states['_world_tfidf'] = _text_to_tfidf(' '.join(appeared))

        if existing:
            existing.character_states = character_states
            existing.world_states = world_states
            existing.foreshadow_status = foreshadow_status
            existing.character_arc_progress = arc_progress
            if chapter.id:
                existing.chapter_id = chapter.id
        else:
            entry = PMConsistencyState(
                project_id=self.project_id,
                chapter_id=chapter.id,
                chapter_number=ch_number,
                character_states=character_states,
                world_states=world_states,
                foreshadow_status=foreshadow_status,
                character_arc_progress=arc_progress,
            )
            self.db.add(entry)

        await self.db.commit()
        logger.info(f'✅ 一致性快照已保存: 第{ch_number}章, {len(character_states)}角色, {len(foreshadow_status)}伏笔')

        return existing or entry

    # ==================== P1: 检查与警报 ====================

    async def check_and_alert(
        self,
        target_chapter_number: int,
    ) -> ConsistencyCheckResult:
        """章节生成前，做一致性检查

        对比前几章快照 + LongNovelGuardian 扫描，输出警告列表
        """
        result = ConsistencyCheckResult()

        # 1. 读取历史快照（前 10 章）
        snapshots_r = await self.db.execute(
            select(PMConsistencyState)
            .where(
                PMConsistencyState.project_id == self.project_id,
                PMConsistencyState.chapter_number < target_chapter_number,
                PMConsistencyState.chapter_number >= target_chapter_number - 10,
            )
            .order_by(PMConsistencyState.chapter_number.asc())
        )
        snapshots = list(snapshots_r.scalars().all())

        # 2. 检测角色状态跳变
        if len(snapshots) >= 2:
            last = snapshots[-1]
            prev = snapshots[-2] if len(snapshots) >= 2 else None

            if prev and last.character_states:
                for char_name, last_state in last.character_states.items():
                    prev_state = prev.character_states.get(char_name, {})
                    # 检测位置突变（跨场景跳跃无过渡）
                    last_loc = (last_state or {}).get('location', '')
                    prev_loc = (prev_state or {}).get('location', '')
                    if last_loc and prev_loc and last_loc != prev_loc:
                        # 检查是否在上一章正文中有过渡描述
                        result.add(
                            ConsistencyIssue(
                                dimension='character_state_jump',
                                severity='medium',
                                description=f'「{char_name}」位置跳跃: {prev_loc} → {last_loc}（需确认有过渡描写）',
                                chapter_number=last.chapter_number,
                                character=char_name,
                                suggestion=f'在「{char_name}」的移动路径中加入过渡描写',
                            )
                        )

        # 3. 世界观漂移检测（章节级规则命中差异 > 50% 才算漂移）
        if len(snapshots) >= 2:
            last_world = snapshots[-1].world_states or {}
            prev_world = snapshots[-2].world_states or {} if len(snapshots) >= 2 else {}
            # P3-1 用 TF-IDF 余弦相似度检测漂移
            last_tfidf = last_world.get('_world_tfidf', {})
            prev_tfidf = prev_world.get('_world_tfidf', {})
            cosine_sim = _cosine_similarity(last_tfidf, prev_tfidf)

            # 兼容旧逻辑：hash 不同 + 余弦相似度 < 0.7 才算真漂移
            if last_world.get('_world_rules_hash') != prev_world.get('_world_rules_hash') and cosine_sim < 0.7:
                # hash 不同时计算规则命中差异率
                last_appeared = set(last_world.get('_appeared_rules', []))
                prev_appeared = set(prev_world.get('_appeared_rules', []))
                union = last_appeared | prev_appeared
                if union:
                    diff_rate = len(last_appeared ^ prev_appeared) / len(union)
                    # 连续 severity：diff_rate 0→0.2→0.5→1.0 → low→medium→high
                    issue_severity = 'low'
                    if diff_rate >= 0.5:
                        issue_severity = 'high'
                    elif diff_rate >= 0.2:
                        issue_severity = 'medium'
                    if issue_severity != 'low':
                        result.add(
                            ConsistencyIssue(
                                dimension='world_drift',
                                severity=issue_severity,
                                description=f'世界观规则命中差异 {diff_rate:.0%}(severity={issue_severity})，可能存在设定漂移',
                                chapter_number=snapshots[-1].chapter_number,
                                suggestion='检查相邻章节是否引入与原世界观冲突的设定',
                            )
                        )

        # 4. 调用 LongNovelGuardian 做深度扫描
        try:
            from app.services.guardian.long_novel_guardian import guardian
            from app.models.story_line import StoryLine

            proj_r = await self.db.execute(select(Project).where(Project.id == self.project_id))
            project = proj_r.scalar_one_or_none()

            ch_r = await self.db.execute(
                select(Chapter)
                .where(
                    Chapter.project_id == self.project_id,
                    Chapter.chapter_number <= target_chapter_number,
                )
                .order_by(Chapter.chapter_number)
            )
            chapters = list(ch_r.scalars().all())

            char_r = await self.db.execute(select(Character).where(Character.project_id == self.project_id))
            chars = list(char_r.scalars().all())

            fore_r = await self.db.execute(select(Foreshadow).where(Foreshadow.project_id == self.project_id))
            foreshadows = list(fore_r.scalars().all())

            sl_r = await self.db.execute(select(StoryLine).where(StoryLine.project_id == self.project_id))
            storylines = list(sl_r.scalars().all())

            if project and chapters:
                report = await guardian.scan(project, chapters, chars, foreshadows, storylines)
                for issue in report.issues:
                    result.add(
                        ConsistencyIssue(
                            dimension=issue.type,
                            severity=issue.severity,
                            description=issue.msg,
                            chapter_number=issue.chapter_number,
                            suggestion=issue.suggestion or '',
                        )
                    )
        except Exception as e:
            logger.warning(f'LongNovelGuardian 扫描异常（非阻塞）: {e}')

        logger.info(f'一致性检查完成: {len(result.issues)} 个问题, passed={result.passed}')
        return result

    # ==================== P3: 健康检查 API ====================

    async def full_health_check(self) -> dict:
        """全项目健康度扫描（实现委托至 pm_guardian_health.full_health_check）"""
        return await _full_health_check(self)

    # ==================== 伏笔状态同步 ====================

    async def sync_foreshadow_state(self) -> int:
        """将当前伏笔表状态同步到最新快照的 foreshadow_status 字段"""
        from app.models.foreshadow import Foreshadow

        # 获取最新快照
        snap_r = await self.db.execute(
            select(PMConsistencyState)
            .where(
                PMConsistencyState.project_id == self.project_id,
            )
            .order_by(PMConsistencyState.chapter_number.desc())
            .limit(1)
        )
        snap = snap_r.scalar_one_or_none()
        if not snap:
            return 0

        # 从伏笔表重新读取所有状态
        fore_r = await self.db.execute(select(Foreshadow).where(Foreshadow.project_id == self.project_id))
        new_status = {}
        for f in fore_r.scalars().all():
            key = f.title or f.id[:8]
            new_status[key] = f.status

        snap.foreshadow_status = new_status
        await self.db.commit()
        logger.info(f'🔮 伏笔状态同步完成: {len(new_status)} 个伏笔 (快照第{snap.chapter_number}章)')
        return len(new_status)

    # ==================== 大纲漂移检测 ====================

    async def detect_outline_drift(
        self,
        old_outline: str | None,
        new_outline: str,
        known_names: set[str] | None = None,
    ) -> list[str]:
        """对比新旧大纲版本，检测实质性变化

        Args:
            old_outline: 旧大纲文本（None 表示首次创建，不报警）
            new_outline: 新大纲文本
            known_names: 项目注册角色名白名单（characters 表）。提供时，
                正则抽取的候选名必须命中白名单才参与角色增减对比，
                防止「化肥到货」等汉字碎片误报；过滤后两侧均为空集则
                跳过角色名对比（空集 ≠ 漂移）。None 保持旧行为（不过滤）。
        """
        if not old_outline:
            return []  # 首次创建不报警

        drifts = []
        # 长度变化超过 30% 视为大幅调整
        old_len = len(old_outline)
        new_len = len(new_outline)
        if old_len > 0:
            ratio = new_len / old_len
            if ratio > 1.5:
                drifts.append(f'大纲篇幅大幅增加 ({old_len}→{new_len} 字符)')
            elif ratio < 0.5:
                drifts.append(f'大纲篇幅大幅缩减 ({old_len}→{new_len} 字符)')

        # 检测关键人物名变更
        import re as _re

        old_names = set(_re.findall(r'[\u4e00-\u9fff]{2,4}(?=[\u3002\uff0c\uff01\u3001\u201c\u201d\u300a\u300b])', old_outline))
        new_names = set(_re.findall(r'[\u4e00-\u9fff]{2,4}(?=[\u3002\uff0c\uff01\u3001\u201c\u201d\u300a\u300b])', new_outline))

        # 白名单过滤：候选名必须对应注册角色才参与对比（生产实证「化肥到货」类碎片误报）
        if known_names is not None:
            old_names = filter_names_by_whitelist(old_names, known_names)
            new_names = filter_names_by_whitelist(new_names, known_names)
            if not old_names and not new_names:
                # 过滤后空集 → 无注册角色参与对比，跳过角色名对比（空集 ≠ 漂移）
                return drifts

        dropped = old_names - new_names
        if dropped:
            drifts.append(f'大纲中移除了角色: {", ".join(list(dropped)[:3])}')
        added = new_names - old_names
        if added:
            drifts.append(f'大纲中新增角色: {", ".join(list(added)[:3])}')

        return drifts


# ==================== 单例 ====================

pm_consistency_guardian = None  # 不直接实例化，每个请求创建新实例
