"""漫剧一致性守护 — 事前上下文注入 + 事中状态门控。

区别于 `domain_engines/comic/` 的 4 个"事后扫描器"（面向 comic_panels 表做全片复核），
本守护器面向生产流水线（Storyboard/Shot/ShotAsset）提供两层前置能力：

- 事前（build_script_context）：分镜生成前，从设定圣经（CharacterCard/SettingBible）
  + 上一集摘要组装结构化上下文块，注入 LLM prompt，从源头减少角色/世界观漂移。
- 事中（gate_transition）：镜头状态机每次转换前做一致性门控，
  不通过则阻塞流水线（如首帧未审核不得进入视频阶段）。

设计遵循项目"最小侵入 + 异常吞掉 + 降级放行"原则：
所有 LLM/多模态调用失败时按"放行 + 记录"处理，绝不因守护逻辑异常阻断生产。
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comic_bible import (
    CharacterCard,
    ComicEpisode,
    SettingBible,
)
from app.models.comic_review import ReviewCheckpoint
from app.models.comic_shot import Shot, ShotAsset
from app.models.pm_consistency_state_comic import PMConsistencyStateComic
from app.services.pm.feature_config import pm_feature_config
from app.services.pm.scanner_base import ScanIssue

logger = logging.getLogger(__name__)

# 语气标记词（复用 dialogue_scanner 规则，作用于 Shot.dialogue 文本）
_FORMAL_MARKERS = {'请', '您', '阁下', '在下', '鄙人', '承蒙', '岂敢'}
_INFORMAL_MARKERS = {'你', '老子', '爷', '俺', '咱', '喂', '哈'}


@dataclass
class GateResult:
    """门控结果 — 事中一致性校验的标准化输出。

    Attributes:
        passed: 是否通过门控
        blocking: True=硬阻塞（拒绝状态转换）；False=软警告（记录但放行）
        issues: 命中的问题列表（ScanIssue）
        summary: 人类可读的汇总描述
        score: 可选一致性评分（视觉门控时写入 Shot.last_consistency_score）
    """

    passed: bool = True
    blocking: bool = False
    issues: list[ScanIssue] = field(default_factory=list)
    summary: str = ''
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'passed': self.passed,
            'blocking': self.blocking,
            'summary': self.summary,
            'score': self.score,
            'issues': [i.to_dict() for i in self.issues],
        }


class ComicConsistencyGuardian:
    """漫剧一致性守护器 — 事前注入 + 事中门控。"""

    def __init__(self) -> None:
        cfg = pm_feature_config.get_comic_guardian_config()
        self.enabled: bool = bool(cfg.get('enabled', True))
        self.block_on_critical: bool = bool(cfg.get('block_on_critical', True))
        try:
            self.visual_threshold: float = float(cfg.get('visual_threshold', 0.7))
        except (TypeError, ValueError):
            self.visual_threshold = 0.7

    # =========================================================================
    # 事前：上下文注入
    # =========================================================================

    async def build_script_context(
        self,
        db: AsyncSession,
        project_id: str,
        episode_id: str | None = None,
    ) -> str:
        """组装分镜生成用的设定圣经上下文块（事前守护）。

        从角色卡（外貌/性格/口癖）、设定圣经（世界观/时代/基调）、
        上一集摘要提取结构化约束，供 StoryboardGenerator 注入 LLM prompt。

        任何异常/无数据均返回空串（降级：不阻断生成）。
        """
        if not self.enabled:
            return ''
        try:
            blocks: list[str] = []

            # 世界观设定
            bible = (await db.execute(
                select(SettingBible)
                .where(SettingBible.project_id == project_id)
                .order_by(SettingBible.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if bible:
                parts = [f'【世界观】{bible.world_name}']
                if bible.time_period:
                    parts.append(f'时代背景：{bible.time_period}')
                if bible.tone:
                    parts.append(f'整体基调：{bible.tone}')
                if bible.summary:
                    parts.append(f'概述：{bible.summary[:300]}')
                blocks.append('；'.join(parts))

            # 角色卡（外貌 + 性格 + 口癖）
            cards = (await db.execute(
                select(CharacterCard)
                .where(CharacterCard.project_id == project_id)
                .order_by(CharacterCard.created_at)
                .limit(30)
            )).scalars().all()
            if cards:
                char_lines = ['【角色设定】']
                for c in cards:
                    seg = [c.name]
                    appearance_bits = [b for b in (c.hair, c.eyes, c.outfit) if b]
                    if appearance_bits:
                        seg.append('外貌：' + '，'.join(appearance_bits))
                    if c.personality:
                        seg.append(f'性格：{c.personality[:80]}')
                    if c.catchphrase:
                        seg.append(f'口癖：{c.catchphrase}')
                    char_lines.append('- ' + '；'.join(seg))
                blocks.append('\n'.join(char_lines))

            # 上一集摘要（前情提要）
            prev_summary = await self._previous_episode_summary(db, project_id, episode_id)
            if prev_summary:
                blocks.append(f'【前情提要】{prev_summary[:400]}')

            context = '\n\n'.join(blocks)
            if context:
                logger.info(
                    '[ComicGuardian] 事前上下文注入 project=%s chars=%d',
                    project_id, len(context),
                )
            return context
        except Exception as e:
            logger.warning('[ComicGuardian] build_script_context 降级放行 project=%s: %s', project_id, e)
            return ''

    async def _previous_episode_summary(
        self, db: AsyncSession, project_id: str, episode_id: str | None
    ) -> str:
        """获取上一集摘要（无则返回空串）。"""
        try:
            if episode_id:
                cur = (await db.execute(
                    select(ComicEpisode).where(ComicEpisode.id == episode_id)
                )).scalar_one_or_none()
                if cur and cur.episode_number:
                    prev = (await db.execute(
                        select(ComicEpisode).where(
                            ComicEpisode.project_id == project_id,
                            ComicEpisode.episode_number == cur.episode_number - 1,
                        )
                    )).scalar_one_or_none()
                    return (prev.summary or '') if prev else ''
            # 无 episode_id：取最新一集摘要作为前情
            latest = (await db.execute(
                select(ComicEpisode)
                .where(ComicEpisode.project_id == project_id)
                .order_by(ComicEpisode.episode_number.desc())
                .limit(1)
            )).scalar_one_or_none()
            return (latest.summary or '') if latest else ''
        except Exception:
            return ''

    # =========================================================================
    # 事中：状态门控
    # =========================================================================

    async def gate_transition(
        self,
        db: AsyncSession,
        shot: Shot,
        target_status: str,
        user_id: str,
    ) -> GateResult:
        """镜头状态转换前的一致性门控（事中守护）。

        按 target_status 分派：
        - pending_image：出图前预检（角色卡覆盖，软警告）
        - pending_review_image：出图后视觉一致性（多模态对比，低分阻塞）
        - pending_video：首帧审核门控（无 approved 审核点则阻塞）
        - 其余：放行

        任何异常均降级为放行（passed=True, blocking=False）。
        """
        if not self.enabled:
            return GateResult(passed=True, summary='守护未启用，放行')
        try:
            if target_status == 'pending_image':
                result = await self._gate_to_image(db, shot, user_id)
                if result.passed:
                    await self._snapshot_after_gate(db, shot, 'pending_image', result)
                return result
            if target_status == 'pending_review_image':
                result = await self._gate_to_review(db, shot, user_id)
                if result.passed:
                    await self._snapshot_after_gate(db, shot, 'pending_review_image', result)
                return result
            if target_status == 'pending_video':
                result = await self._gate_to_video(db, shot, user_id)
                if result.passed:
                    await self._snapshot_after_gate(db, shot, 'pending_video', result)
                return result
            return GateResult(passed=True, summary='无需门控，放行')
        except Exception as e:
            logger.warning(
                '[ComicGuardian] gate_transition 降级放行 shot=%s target=%s: %s',
                getattr(shot, 'id', '?'), target_status, e,
            )
            return GateResult(passed=True, summary=f'门控异常降级放行: {e}')

    async def _snapshot_after_gate(
        self,
        db: AsyncSession,
        shot: Shot,
        gate_name: str,
        result: GateResult | None = None,
    ) -> None:
        """门控通过后写入漫剧一致性快照（upsert，一镜一条）。

        采集该镜头门控时刻的状态：
        - character_visual_states: 镜头引用角色的定稿外貌（来自 CharacterCard）
        - scene_state: 场景类型 + 画面描述
        - camera_state: 镜头运动 + 景别
        - forward: 与前一镜的衔接（前镜号 + 视觉相似度评分）
        - backward_consistency_score: 本次门控的视觉一致性评分
        - global_sequence: 镜头号（作为全局序列基准）

        任何异常静默降级（仅记日志），绝不阻断门控主流程。
        """
        try:
            # 角色视觉状态：镜头引用角色 → 查角色卡取外貌
            char_visual: dict[str, dict] = {}
            meta = getattr(shot, 'metadata_json', None)
            matched = meta.get('matched_characters', []) if isinstance(meta, dict) else []
            if matched:
                cards = (await db.execute(
                    select(CharacterCard).where(
                        CharacterCard.project_id == shot.project_id,
                        CharacterCard.name.in_(matched),
                    )
                )).scalars().all()
                for c in cards:
                    bits = [b for b in (c.hair, c.eyes, c.outfit) if b]
                    char_visual[c.name] = {'appearance': '，'.join(bits)}

            scene_state = {
                'scene_type': shot.scene_type or '',
                'visual_description': (shot.visual_description or '')[:200],
            }
            camera_state = {
                'camera_movement': shot.camera_movement or '',
                'scene_type': shot.scene_type or '',
            }
            forward = {}
            if shot.shot_number and shot.shot_number > 1:
                # 前一镜号（同一分镜表内）
                prev_sn = shot.shot_number - 1
                forward['prev_shot_number'] = prev_sn
            if result is not None and result.score is not None:
                forward['similarity'] = result.score

            # 存在则更新，否则插入（UniqueConstraint project_id+shot_id）
            existing = (await db.execute(
                select(PMConsistencyStateComic).where(
                    PMConsistencyStateComic.project_id == shot.project_id,
                    PMConsistencyStateComic.shot_id == shot.id,
                )
            )).scalar_one_or_none()

            if existing:
                existing.character_visual_states = char_visual
                existing.scene_state = scene_state
                existing.camera_state = camera_state
                existing.forward = forward
                if result is not None and result.score is not None:
                    existing.backward_consistency_score = result.score
                existing.global_sequence = shot.shot_number
                db.add(existing)
            else:
                db.add(PMConsistencyStateComic(
                    project_id=shot.project_id,
                    episode_id=getattr(shot, 'episode_id', None),
                    shot_id=shot.id,
                    shot_number=shot.shot_number,
                    character_visual_states=char_visual,
                    scene_state=scene_state,
                    camera_state=camera_state,
                    forward=forward,
                    backward_consistency_score=result.score if result is not None else None,
                    global_sequence=shot.shot_number,
                ))
            await db.flush()
            logger.info('[ComicGuardian] 一致性快照写入 shot=%s gate=%s', shot.id, gate_name)
        except Exception as e:
            logger.warning('[ComicGuardian] 快照写入降级跳过 shot=%s: %s', getattr(shot, 'id', '?'), e)

    async def _gate_to_image(self, db: AsyncSession, shot: Shot, user_id: str) -> GateResult:
        """出图前预检 — 校验镜头引用的角色是否已建立角色卡。

        缺角色卡 → 软警告（外貌可能漂移），不硬阻塞（项目可后补卡）。
        """
        issues: list[ScanIssue] = []
        matched: list[str] = []
        meta = getattr(shot, 'metadata_json', None)
        if isinstance(meta, dict):
            matched = meta.get('matched_characters', []) or []

        if matched:
            cards = (await db.execute(
                select(CharacterCard.name).where(
                    CharacterCard.project_id == shot.project_id,
                    CharacterCard.name.in_(matched),
                )
            )).scalars().all()
            card_names = set(cards)
            missing = [n for n in matched if n not in card_names]
            for name in missing:
                issues.append(ScanIssue(
                    issue_type='ca_character_card_missing',
                    severity='warning',
                    message=f'镜头 #{shot.shot_number} 引用角色「{name}」但无角色卡，出图外貌可能漂移',
                    entities=[f'character:{name}', f'shot:{shot.shot_number}'],
                    metadata={'character': name, 'shot_id': shot.id},
                ))

        if issues:
            return GateResult(
                passed=False,
                blocking=False,  # 软警告：不阻断出图
                issues=issues,
                summary=f'{len(issues)} 个角色缺角色卡（软警告）',
            )
        return GateResult(passed=True, summary='出图前预检通过')

    async def _gate_to_review(self, db: AsyncSession, shot: Shot, user_id: str) -> GateResult:
        """出图后视觉一致性门控 — 与相邻镜对比图片。

        多模态可用且存在相邻镜图片时对比评分，低于阈值 → 阻塞（可配置）。
        无多模态/无相邻图 → 放行。
        """
        curr_img = await self._latest_asset_url(db, shot.id, 'image')
        if not curr_img:
            return GateResult(passed=True, summary='无图片素材，放行')

        prev_img, prev_number = await self._adjacent_shot_image(db, shot)
        if not prev_img:
            return GateResult(passed=True, summary='无相邻镜图片可对比，放行')

        try:
            from app.services.multimodal import get_multimodal_service
            mm = get_multimodal_service()
            if not mm.is_available:
                return GateResult(passed=True, summary='多模态未启用，跳过视觉门控')

            result = await mm.compare_images(prev_img, curr_img)
            score = result.consistency_score
            # 回写一致性评分（供前端展示）
            try:
                shot.last_consistency_score = score
            except Exception:
                pass

            if score < self.visual_threshold:
                issue = ScanIssue(
                    issue_type='ca_visual_inconsistency',
                    severity='critical',
                    message=(
                        f'镜头 #{prev_number}→#{shot.shot_number} 视觉相似度低 '
                        f'({score:.0%})，疑似角色外貌/画风不一致'
                    ),
                    entities=[f'shot:{prev_number}', f'shot:{shot.shot_number}'],
                    metadata={
                        'consistency_score': score,
                        'shot_id': shot.id,
                        'differences': result.issues,
                        'backend': result.backend,
                    },
                )
                return GateResult(
                    passed=False,
                    blocking=self.block_on_critical,
                    issues=[issue],
                    summary=f'视觉一致性 {score:.0%} 低于阈值 {self.visual_threshold:.0%}',
                    score=score,
                )
            return GateResult(
                passed=True,
                summary=f'视觉一致性 {score:.0%} 达标',
                score=score,
            )
        except Exception as e:
            logger.warning('[ComicGuardian] 视觉门控降级放行 shot=%s: %s', shot.id, e)
            return GateResult(passed=True, summary=f'视觉门控异常降级放行: {e}')

    async def _gate_to_video(self, db: AsyncSession, shot: Shot, user_id: str) -> GateResult:
        """进入视频阶段前 — 首帧审核门控。

        要求存在 approved 的 first_frame 审核点，否则阻塞（人工确认是产品核心环节）。
        """
        review = (await db.execute(
            select(ReviewCheckpoint).where(
                ReviewCheckpoint.target_type == 'shot',
                ReviewCheckpoint.target_id == shot.id,
                ReviewCheckpoint.review_type == 'first_frame',
            )
        )).scalars().all()

        if not review:
            issue = ScanIssue(
                issue_type='ca_review_missing',
                severity='critical',
                message=f'镜头 #{shot.shot_number} 尚无首帧审核点，需人工确认首帧后方可进入视频阶段',
                entities=[f'shot:{shot.shot_number}'],
                metadata={'shot_id': shot.id, 'required_review': 'first_frame'},
            )
            return GateResult(
                passed=False,
                blocking=self.block_on_critical,
                issues=[issue],
                summary='缺少首帧审核点',
            )

        approved = any(r.status == 'approved' for r in review)
        if not approved:
            statuses = ','.join(sorted({r.status for r in review}))
            issue = ScanIssue(
                issue_type='ca_review_not_approved',
                severity='critical',
                message=f'镜头 #{shot.shot_number} 首帧审核未通过（当前状态：{statuses}）',
                entities=[f'shot:{shot.shot_number}'],
                metadata={'shot_id': shot.id, 'review_status': statuses},
            )
            return GateResult(
                passed=False,
                blocking=self.block_on_critical,
                issues=[issue],
                summary='首帧审核未通过',
            )

        return GateResult(passed=True, summary='首帧审核已通过')

    # =========================================================================
    # 事中：分镜表批量门控（confirm_storyboard 用）
    # =========================================================================

    async def gate_storyboard_confirm(
        self,
        db: AsyncSession,
        storyboard_id: str,
        project_id: str,
        user_id: str,
    ) -> GateResult:
        """分镜表确认（pending_script → pending_image）批量门控。

        对表内所有 pending_script 镜头做角色卡覆盖检查 + 跨镜对话语气跳变检查。
        汇总软/硬问题；硬问题（blocking）用于阻止确认。
        """
        if not self.enabled:
            return GateResult(passed=True, summary='守护未启用，放行')
        try:
            shots = (await db.execute(
                select(Shot)
                .where(
                    Shot.storyboard_id == storyboard_id,
                    Shot.status == 'pending_script',
                )
                .order_by(Shot.shot_number)
            )).scalars().all()

            issues: list[ScanIssue] = []
            # 角色卡覆盖（逐镜软警告）
            for shot in shots:
                res = await self._gate_to_image(db, shot, user_id)
                issues.extend(res.issues)
            # 跨镜对话语气跳变
            issues.extend(self._check_dialogue_style(shots))

            blocking_issues = [i for i in issues if i.severity == 'critical']
            if blocking_issues and self.block_on_critical:
                return GateResult(
                    passed=False,
                    blocking=True,
                    issues=issues,
                    summary=f'{len(blocking_issues)} 个阻塞性问题，分镜确认被拦截',
                )
            if issues:
                return GateResult(
                    passed=True,
                    blocking=False,
                    issues=issues,
                    summary=f'{len(issues)} 个软警告（放行）',
                )
            return GateResult(passed=True, summary='分镜确认门控通过')
        except Exception as e:
            logger.warning('[ComicGuardian] gate_storyboard_confirm 降级放行 sb=%s: %s', storyboard_id, e)
            return GateResult(passed=True, summary=f'门控异常降级放行: {e}')

    def _check_dialogue_style(self, shots: list[Shot]) -> list[ScanIssue]:
        """跨镜对话语气跳变检查（规则版，复用 dialogue_scanner 逻辑）。"""
        issues: list[ScanIssue] = []
        try:
            # 按角色聚合语气序列：[(shot_number, style)]
            char_styles: dict[str, list[tuple[int, str]]] = {}
            for shot in shots:
                dialogue = (shot.dialogue or '').strip()
                if not dialogue:
                    continue
                meta = shot.metadata_json if isinstance(shot.metadata_json, dict) else {}
                names = meta.get('matched_characters', []) or []
                style = self._classify_style(dialogue)
                # 无法归属角色时以镜头为单位跳过（避免误报）
                for name in names:
                    char_styles.setdefault(name, []).append((shot.shot_number, style))

            for name, seq in char_styles.items():
                for i in range(1, len(seq)):
                    prev_no, prev_style = seq[i - 1]
                    curr_no, curr_style = seq[i]
                    if prev_style != curr_style and prev_style and curr_style:
                        issues.append(ScanIssue(
                            issue_type='ca_dialogue_inconsistency',
                            severity='warning',
                            message=(
                                f'角色「{name}」语气跳变：{prev_style}→{curr_style} '
                                f'(镜头 #{prev_no}→#{curr_no})'
                            ),
                            entities=[f'character:{name}', f'shot:{prev_no}', f'shot:{curr_no}'],
                            metadata={
                                'character': name,
                                'style_from': prev_style,
                                'style_to': curr_style,
                            },
                        ))
        except Exception as e:
            logger.debug('[ComicGuardian] 对话语气检查跳过: %s', e)
        return issues

    @staticmethod
    def _classify_style(text: str) -> str:
        """简单规则分类对话语气风格（formal/informal/neutral）。"""
        formal = sum(1 for m in _FORMAL_MARKERS if m in text)
        informal = sum(1 for m in _INFORMAL_MARKERS if m in text)
        if formal > informal:
            return 'formal'
        if informal > formal:
            return 'informal'
        return 'neutral'

    # =========================================================================
    # 素材辅助
    # =========================================================================

    async def _latest_asset_url(self, db: AsyncSession, shot_id: str, asset_type: str) -> str | None:
        """获取镜头某类型素材的最新版本 URL。"""
        try:
            asset = (await db.execute(
                select(ShotAsset)
                .where(
                    ShotAsset.shot_id == shot_id,
                    ShotAsset.asset_type == asset_type,
                )
                .order_by(ShotAsset.version.desc())
                .limit(1)
            )).scalar_one_or_none()
            return asset.file_url if asset and asset.file_url else None
        except Exception:
            return None

    async def _adjacent_shot_image(
        self, db: AsyncSession, shot: Shot
    ) -> tuple[str | None, int | None]:
        """获取同一分镜表内前一镜头（shot_number-1）的图片 URL 与镜号。"""
        try:
            prev = (await db.execute(
                select(Shot).where(
                    Shot.storyboard_id == shot.storyboard_id,
                    Shot.shot_number == shot.shot_number - 1,
                ).limit(1)
            )).scalar_one_or_none()
            if not prev:
                return None, None
            url = await self._latest_asset_url(db, prev.id, 'image')
            return url, prev.shot_number
        except Exception:
            return None, None


# 模块级单例（无状态依赖，可复用）
_guardian_singleton: ComicConsistencyGuardian | None = None


def get_comic_guardian() -> ComicConsistencyGuardian:
    """获取漫剧一致性守护器单例。"""
    global _guardian_singleton
    if _guardian_singleton is None:
        _guardian_singleton = ComicConsistencyGuardian()
    return _guardian_singleton
