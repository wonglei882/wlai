"""漫剧质量评分器 — 6 维规则评分，低于阈值输出 issue。

对漫剧项目的分镜数据做整体质量体检，输出 6 个维度得分：
- visual_diversity      视觉多样性（景别/角度/转场/镜头运动组合的丰富度）
- dialogue_density      对白密度（有对白的分镜占比，过稀/过密均扣分）
- panel_rhythm          分镜节奏（镜头时长合理性 + 全局序列连续性）
- information_density   信息密度（画面描述平均长度，过短说明信息不足）
- readability           可读性（台词平均长度，超过 15 字上限扣分）
- character_coverage    角色覆盖度（角色卡在分镜中的出场覆盖率）

总分低于 PASS_THRESHOLD 时生成 ScanIssue(issue_type='ca_quality_low')。
纯规则评分（不调 AI），保证巡检链路确定性与可测试性。
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comic import ComicPanel
from app.models.comic_bible import CharacterCard
from app.models.comic_shot import Shot
from app.services.pm.scanner_base import BaseScanner, ScanIssue

logger = logging.getLogger(__name__)

# 台词最大字数（与 storyboard_gen.MAX_DIALOGUE_CHARS 对齐）
MAX_DIALOGUE_CHARS = 15
# 理想镜头时长（与 storyboard_gen.DEFAULT_SHOT_DURATION 对齐）
IDEAL_SHOT_DURATION = 4.0
# 时长合理区间（秒）
DURATION_OK_RANGE = (3.0, 5.0)
# 总分及格线（低于此值生成 issue，与 novel quality_score 阈值一致）
PASS_THRESHOLD = 70.0
# 单维低分线（低于此值记入 low_dims）
LOW_DIM_THRESHOLD = 60.0
# 数据采样上限（防止全表扫描）
SAMPLE_LIMIT = 100

# 6 维权重（和为 1.0，当前等权）
DIMENSION_WEIGHTS: dict[str, float] = {
    'visual_diversity': 1 / 6,
    'dialogue_density': 1 / 6,
    'panel_rhythm': 1 / 6,
    'information_density': 1 / 6,
    'readability': 1 / 6,
    'character_coverage': 1 / 6,
}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """夹取到 [lo, hi]。"""
    return max(lo, min(hi, value))


class ComicQualityScorer(BaseScanner):
    """漫剧质量评分器 — 6 维规则评分扫描。"""

    name = 'comic_quality_score'
    issue_type = 'ca_quality_low'

    async def scan(
        self, db: AsyncSession, project_id: str, user_id: str
    ) -> list[ScanIssue]:
        """对项目分镜数据执行 6 维质量评分，总分低于阈值生成 issue。"""
        issues: list[ScanIssue] = []
        try:
            panels = (
                await db.execute(
                    select(ComicPanel)
                    .where(ComicPanel.project_id == project_id)
                    .order_by(ComicPanel.global_sequence)
                    .limit(SAMPLE_LIMIT)
                )
            ).scalars().all()
            shots = (
                await db.execute(
                    select(Shot)
                    .where(Shot.project_id == project_id)
                    .order_by(Shot.shot_number)
                    .limit(SAMPLE_LIMIT)
                )
            ).scalars().all()
            cards = (
                await db.execute(
                    select(CharacterCard).where(CharacterCard.project_id == project_id)
                )
            ).scalars().all()
        except Exception as e:
            logger.warning('[CA] 质量评分数据加载异常 project=%s: %s', project_id, e)
            return issues

        # 无任何分镜/镜头数据 → 无从评分，静默返回
        if not panels and not shots:
            return issues

        scores = self._compute_scores(panels, shots, cards)

        low_dims = [
            dim for dim, sc in scores.items()
            if sc < LOW_DIM_THRESHOLD
        ]
        total = round(
            sum(scores.get(dim, 0.0) * w for dim, w in DIMENSION_WEIGHTS.items()),
            1,
        )

        if total < PASS_THRESHOLD:
            issues.append(
                ScanIssue(
                    issue_type='ca_quality_low',
                    severity='warning',
                    message=(
                        f'漫剧质量评分 {total:.1f}/100 低于阈值 {PASS_THRESHOLD:.0f}，'
                        f'低分维度: {";".join(low_dims) if low_dims else "无"}'
                    ),
                    entities=[f'project:{project_id}'],
                    metadata={
                        'scores': scores,
                        'total_score': total,
                        'low_dims': low_dims,
                        'score_threshold': PASS_THRESHOLD,
                    },
                )
            )
        return issues

    def to_diagnostic_message(self, issue: ScanIssue) -> str:
        return f'[CA] {issue.message}'

    # ------------------------------------------------------------------
    # 维度计算
    # ------------------------------------------------------------------

    def _compute_scores(
        self,
        panels: list[ComicPanel],
        shots: list[Shot],
        cards: list[CharacterCard],
    ) -> dict[str, float]:
        """计算 6 维得分（各 0-100）。"""
        return {
            'visual_diversity': self._score_visual_diversity(panels, shots),
            'dialogue_density': self._score_dialogue_density(panels, shots),
            'panel_rhythm': self._score_panel_rhythm(panels, shots),
            'information_density': self._score_information_density(panels, shots),
            'readability': self._score_readability(panels, shots),
            'character_coverage': self._score_character_coverage(panels, shots, cards),
        }

    @staticmethod
    def _score_visual_diversity(
        panels: list[ComicPanel], shots: list[Shot]
    ) -> float:
        """视觉多样性：额外视觉组合占比，全部雷同 → 0，全部不同 → 100。"""
        combos: set[tuple[str, ...]] = set()
        for p in panels:
            combos.add(('panel', p.camera_angle or '', p.transition_type or ''))
        for s in shots:
            combos.add(('shot', s.scene_type or '', s.camera_movement or ''))
        total = len(panels) + len(shots)
        if total <= 1:
            # 单一数据源无从比较 → 中性分
            return 100.0
        # (unique-1)/(total-1)：额外组合的比例；全部相同 = 0，完全区分 = 100
        return round(_clamp((len(combos) - 1) / (total - 1) * 100.0), 1)

    @staticmethod
    def _score_dialogue_density(
        panels: list[ComicPanel], shots: list[Shot]
    ) -> float:
        """对白密度：有对白的分镜占比，理想值 0.6。"""
        if panels:
            with_dialogue = sum(
                1 for p in panels
                if p.dialogue and any(
                    isinstance(d, dict) and d.get('text')
                    for d in p.dialogue
                )
            )
            ratio = with_dialogue / len(panels)
        else:
            # 无面板数据时退化为镜头对白占比（Shot.dialogue 为字符串）
            with_dialogue = sum(1 for s in shots if s.dialogue)
            ratio = with_dialogue / len(shots) if shots else 0.5
        return round(_clamp(100.0 - abs(ratio - 0.6) * 200.0), 1)

    @staticmethod
    def _score_panel_rhythm(
        panels: list[ComicPanel], shots: list[Shot]
    ) -> float:
        """分镜节奏：镜头时长合理性（50%）+ 序列连续性（50%）。"""
        durations = [s.duration for s in shots if s.duration]
        if durations:
            avg_d = sum(durations) / len(durations)
            if DURATION_OK_RANGE[0] <= avg_d <= DURATION_OK_RANGE[1]:
                dur_score = 100.0
            else:
                dur_score = _clamp(100.0 - abs(avg_d - IDEAL_SHOT_DURATION) * 50.0)
        else:
            # 无时长数据 → 中性分（不扣分）
            dur_score = 70.0

        seqs = sorted(
            p.global_sequence for p in panels if p.global_sequence is not None
        )
        if len(seqs) >= 2:
            gaps = sum(1 for a, b in zip(seqs, seqs[1:], strict=False) if b != a + 1)
            seq_score = _clamp(100.0 - gaps * 20.0)
        else:
            seq_score = 70.0

        return round(dur_score * 0.5 + seq_score * 0.5, 1)

    @staticmethod
    def _score_information_density(
        panels: list[ComicPanel], shots: list[Shot]
    ) -> float:
        """信息密度：画面描述平均长度（50 字即满分）。"""
        texts = [
            p.scene_description for p in panels if p.scene_description
        ] + [
            s.visual_description for s in shots if s.visual_description
        ]
        if not texts:
            # 无描述数据 → 中性分（不扣分）
            return 70.0
        avg_len = sum(len(t) for t in texts) / len(texts)
        return round(_clamp(avg_len * 2.0), 1)

    @staticmethod
    def _score_readability(
        panels: list[ComicPanel], shots: list[Shot]
    ) -> float:
        """可读性：台词平均长度，超过 15 字上限逐字扣分。"""
        texts = [
            d.get('text')
            for p in panels
            for d in (p.dialogue or [])
            if isinstance(d, dict) and d.get('text')
        ]
        # 镜头台词（Shot.dialogue 为字符串列）一并计入
        texts += [s.dialogue for s in shots if s.dialogue]
        if not texts:
            # 无台词 → 中性分（不扣分）
            return 70.0
        avg = sum(len(t) for t in texts) / len(texts)
        if avg <= MAX_DIALOGUE_CHARS:
            return 100.0
        return round(_clamp(100.0 - (avg - MAX_DIALOGUE_CHARS) * 6.0), 1)

    @staticmethod
    def _score_character_coverage(
        panels: list[ComicPanel],
        shots: list[Shot],
        cards: list[CharacterCard],
    ) -> float:
        """角色覆盖度：角色卡在分镜/镜头/对白中的出场覆盖率。"""
        card_names = [c.name for c in cards]
        if not card_names:
            # 无角色卡 → 中性分（不扣分）
            return 70.0

        appearing: set[str] = set()
        for p in panels:
            for cv in (p.characters_visual or []):
                if isinstance(cv, dict) and cv.get('name'):
                    appearing.add(cv['name'])
            for d in (p.dialogue or []):
                if isinstance(d, dict) and d.get('character'):
                    appearing.add(d['character'])
        for s in shots:
            matched = (s.metadata_json or {}).get('matched_characters', [])
            appearing.update(matched)

        covered = sum(1 for name in card_names if name in appearing)
        return round(covered / len(card_names) * 100.0, 1)