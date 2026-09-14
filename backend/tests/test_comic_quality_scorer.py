"""漫剧质量评分器（ComicQualityScorer）单元测试。

覆盖：
- 6 维评分计算（视觉多样性/对白密度/分镜节奏/信息密度/可读性/角色覆盖度）
- 总分享阈值生成 ca_quality_low issue（含 scores/low_dims/total_score metadata）
- 高质量项目不触发 issue
- 空项目（无分镜/镜头）静默跳过
- 无角色卡时角色覆盖度中性分（不误报）
"""
import pytest
from app.domain_engines.comic.quality_scorer import (
    PASS_THRESHOLD,
    ComicQualityScorer,
)
from app.models.comic import ComicPanel
from app.models.comic_bible import CharacterCard
from app.models.comic_shot import Shot, Storyboard


def _make_storyboard(project_id: str = 'proj-1', user_id: str = 'u-1'):
    return Storyboard(
        project_id=project_id, user_id=user_id,
        title='测试分镜表', source_text='测试文本',
        shot_count=1, status='draft',
    )


def _make_panel(
    project_id: str = 'proj-1', user_id: str = 'u-1', seq: int = 1,
    angle: str = 'medium', transition: str = 'cut',
    scene_description: str = '宗门大殿，云雾缭绕，阳光透过穹顶洒落，弟子们屏息凝神',
    dialogue: list | None = None,
    characters: list | None = None,
):
    return ComicPanel(
        project_id=project_id, user_id=user_id,
        page_number=(seq - 1) // 3 + 1, panel_number=(seq - 1) % 3 + 1,
        global_sequence=seq,
        scene_description=scene_description,
        camera_angle=angle, transition_type=transition,
        characters_visual=characters or [],
        dialogue=dialogue or [],
    )


def _make_shot(
    storyboard_id: str,
    project_id: str = 'proj-1', user_id: str = 'u-1',
    shot_number: int = 1, duration: float = 4.0,
    scene_type: str = '中景', camera_movement: str = '推',
    visual_description: str = '宗门大殿，云雾缭绕，阳光透过穹顶洒落，弟子们屏息凝神',
    dialogue: str = '',
    matched_characters: list | None = None,
):
    return Shot(
        project_id=project_id, user_id=user_id,
        storyboard_id=storyboard_id, shot_number=shot_number,
        duration=duration, scene_type=scene_type,
        visual_description=visual_description, dialogue=dialogue,
        camera_movement=camera_movement, status='pending_script',
        metadata_json={'matched_characters': matched_characters or []},
    )


def _make_character_card(
    project_id: str = 'proj-1', user_id: str = 'u-1', name: str = '林风',
):
    return CharacterCard(
        project_id=project_id, user_id=user_id, name=name,
        hair='黑色长发', eyes='红瞳', outfit='青色道袍',
        personality='沉稳冷静', catchphrase='天道不可违',
        status='approved',
    )


async def _score_project(db_session, panels, shots, cards):
    """向 db_session 插入数据后运行扫描器。"""
    for p in panels:
        db_session.add(p)
    for s in shots:
        db_session.add(s)
    for c in cards:
        db_session.add(c)
    await db_session.flush()

    scorer = ComicQualityScorer()
    return await scorer.scan(db_session, 'proj-1', 'u-1')


def _seed_high_quality(project_id: str = 'proj-1', user_id: str = 'u-1'):
    """高质量项目种子：视觉多样、对白密度适中、节奏均匀、描述充实、角色全覆盖。"""
    angles = ['close_up', 'medium', 'wide', 'bird_eye', 'medium', 'wide']
    transitions = ['cut', 'fade', 'dissolve', 'slide', 'cut', 'fade']
    scenes = ['特写', '近景', '中景', '全景', '近景', '全景']
    cams = ['推', '拉', '摇', '固定', '固定', '推']
    desc = '宗门大殿，云雾缭绕，阳光透过穹顶洒落，弟子们屏息凝神，气氛庄严肃穆'

    sb = _make_storyboard(project_id, user_id)
    panels = [
        _make_panel(
            project_id, user_id, seq=i + 1, angle=angles[i], transition=transitions[i],
            scene_description=desc,
            dialogue=([{'character': '林风', 'text': '天道不可违'}] if i % 2 == 0 else []),
            characters=[{'name': '林风', 'appearance': '黑色长发'}],
        )
        for i in range(6)
    ]
    shots = [
        _make_shot(
            storyboard_id='sb-1', project_id=project_id, user_id=user_id,
            shot_number=i + 1, duration=4.0,
            scene_type=scenes[i], camera_movement=cams[i],
            visual_description=desc, dialogue='',
            matched_characters=['林风'],
        )
        for i in range(6)
    ]
    cards = [_make_character_card(project_id, user_id, '林风')]
    return sb, panels, shots, cards


class TestScoring:
    """6 维评分计算。"""

    @pytest.mark.asyncio
    async def test_happy_path_no_issue(self, db_session):
        """高质量项目 → 总分达标，无 issue。"""
        sb, panels, shots, cards = _seed_high_quality()
        db_session.add(sb)
        issues = await _score_project(db_session, panels, shots, cards)

        assert issues == []

    @pytest.mark.asyncio
    async def test_low_total_emits_issue_with_metadata(self, db_session):
        """全维度低分项目 → 生成 ca_quality_low issue，metadata 含 scores/low_dims。"""
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()
        # 视觉单一 + 无对白 + 短描述 + 超长台词 + 角色未覆盖 + 序列跳号
        panels = [
            _make_panel(
                seq=1, angle='close_up', transition='cut',
                scene_description='短', dialogue=[], characters=[],
            ),
            _make_panel(
                seq=2, angle='close_up', transition='cut',
                scene_description='短', dialogue=[], characters=[],
            ),
            _make_panel(
                seq=4, angle='close_up', transition='cut',
                scene_description='短', dialogue=[], characters=[],
            ),
            _make_panel(
                seq=5, angle='close_up', transition='cut',
                scene_description='短', dialogue=[], characters=[],
            ),
        ]
        shot = _make_shot(
            storyboard_id=sb.id, duration=6.0, scene_type='中景',
            camera_movement='固定', visual_description='短',
            dialogue='这台词实在是太长了多达三十余字严重超出十五字上限要求',
            matched_characters=['林风'],
        )
        cards = [
            _make_character_card('proj-1', 'u-1', '林风'),
            _make_character_card('proj-1', 'u-1', '云岚'),
            _make_character_card('proj-1', 'u-1', '苏晚'),
        ]

        issues = await _score_project(db_session, panels, [shot], cards)

        assert len(issues) == 1
        issue = issues[0]
        assert issue.issue_type == 'ca_quality_low'
        assert issue.severity == 'warning'
        scores = issue.metadata['scores']
        assert set(scores.keys()) == {
            'visual_diversity', 'dialogue_density', 'panel_rhythm',
            'information_density', 'readability', 'character_coverage',
        }
        # visual_diversity: 2 种组合 / 5 数据源
        assert scores['visual_diversity'] < 60
        assert scores['dialogue_density'] < 60
        assert scores['information_density'] < 60
        # readability: 台词超 15 字
        assert scores['readability'] < 60
        # character_coverage: 6 分镜仅 1 角色覆卡出现 × 3 张卡 → <60
        assert scores['character_coverage'] < 60
        assert issue.metadata['total_score'] < PASS_THRESHOLD
        assert 'visual_diversity' in issue.metadata['low_dims']
        assert issue.metadata['score_threshold'] == PASS_THRESHOLD


class TestDimensionScores:
    """单维分数验证。"""

    @pytest.mark.asyncio
    async def test_visual_diversity_single_combo_low(self, db_session):
        """全部面板同角度同转场 → visual_diversity 低分。"""
        panels = [
            _make_panel(seq=i + 1, angle='close_up', transition='cut')
            for i in range(4)
        ]
        shot = _make_shot(storyboard_id='sb-1', scene_type='中景', camera_movement='固定')
        cards = [_make_character_card()]

        issues = await _score_project(db_session, panels, [shot], cards)

        assert len(issues) == 1
        scores = issues[0].metadata['scores']
        assert scores['visual_diversity'] < 60, scores

    @pytest.mark.asyncio
    async def test_dialogue_density_absent_low(self, db_session):
        """全无对白 → dialogue_density 低分。"""
        panels = [
            _make_panel(seq=i + 1, dialogue=[]) for i in range(4)
        ]
        cards = [_make_character_card()]

        issues = await _score_project(db_session, panels, [], cards)

        assert len(issues) == 1
        scores = issues[0].metadata['scores']
        assert scores['dialogue_density'] < 60, scores

    @pytest.mark.asyncio
    async def test_readability_overlong_dialogue_low(self, db_session):
        """台词普遍超长 → readability 低分。"""
        panels = [
            _make_panel(seq=i + 1, dialogue=[{'character': '林风', 'text': '这' * 30}])
            for i in range(3)
        ]
        cards = [_make_character_card()]

        issues = await _score_project(db_session, panels, [], cards)

        assert len(issues) == 1
        scores = issues[0].metadata['scores']
        assert scores['readability'] < 60, scores

    @pytest.mark.asyncio
    async def test_character_coverage_neutral_without_cards(self, db_session):
        """无角色卡 → character_coverage 中性分，不触发 issue（仅其余维度判断）。"""
        # 每面板有对白但视觉单一 → 确保有数据
        panels = [
            _make_panel(
                seq=i + 1, angle='close_up', transition='cut',
                dialogue=[{'character': '林风', 'text': '天道不可违'}],
            )
            for i in range(4)
        ]

        issues = await _score_project(db_session, panels, [], [])

        if issues:
            scores = issues[0].metadata['scores']
            assert 'character_coverage' not in issues[0].metadata['low_dims'], scores


class TestEmptyProject:
    """无数据项目。"""

    @pytest.mark.asyncio
    async def test_no_panels_no_shots_skips(self, db_session):
        """项目无分镜/镜头数据 → 静默跳过，无 issue。"""
        scorer = ComicQualityScorer()
        issues = await scorer.scan(db_session, 'proj-1', 'u-1')

        assert issues == []