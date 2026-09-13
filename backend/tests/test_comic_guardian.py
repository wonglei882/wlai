"""漫剧一致性守护器（ComicConsistencyGuardian）单元测试。

覆盖:
- build_script_context: 事前上下文注入（角色外貌/性格/前情/世界观）
- gate_transition: 事中状态门控（各 target_status 分派 + 阻塞/放行边界）
- gate_storyboard_confirm: 分镜表批量门控
- 降级安全: 守护未启用时放行
"""
import pytest
import pytest_asyncio

from app.models.comic_bible import CharacterCard, SettingBible, ComicEpisode
from app.models.comic_shot import Storyboard, Shot, ShotAsset
from app.models.comic_review import ReviewCheckpoint
from app.services.comic.consistency_guardian import (
    ComicConsistencyGuardian,
    GateResult,
)


# =============================================================================
# 辅助工厂
# =============================================================================

def _make_setting_bible(project_id: str = 'proj-1', user_id: str = 'u-1'):
    return SettingBible(
        project_id=project_id,
        user_id=user_id,
        world_name='修仙大陆',
        summary='灵气充沛的修仙世界',
        time_period='架空古代',
        tone='热血',
    )


def _make_character_card(
    project_id: str = 'proj-1',
    user_id: str = 'u-1',
    name: str = '林风',
    hair: str = '黑色长发',
    eyes: str = '红瞳',
    outfit: str = '青色道袍',
    personality: str = '沉稳冷静',
    catchphrase: str = '天道不可违',
):
    return CharacterCard(
        project_id=project_id,
        user_id=user_id,
        name=name,
        hair=hair,
        eyes=eyes,
        outfit=outfit,
        personality=personality,
        catchphrase=catchphrase,
    )


def _make_storyboard(project_id: str = 'proj-1', user_id: str = 'u-1'):
    return Storyboard(
        project_id=project_id,
        user_id=user_id,
        title='测试分镜表',
        source_text='测试文本',
        shot_count=2,
        status='draft',
    )


def _make_shot(
    storyboard_id: str,
    project_id: str = 'proj-1',
    user_id: str = 'u-1',
    shot_number: int = 1,
    status: str = 'pending_script',
    dialogue: str = '',
    matched_characters: list[str] | None = None,
):
    return Shot(
        project_id=project_id,
        user_id=user_id,
        storyboard_id=storyboard_id,
        shot_number=shot_number,
        duration=4.0,
        scene_type='中景',
        visual_description='画面描述',
        character_action='角色动作',
        dialogue=dialogue,
        sound_effect='',
        camera_movement='固定',
        status=status,
        metadata_json={'matched_characters': matched_characters or []},
    )


# =============================================================================
# 测试: build_script_context（事前上下文注入）
# =============================================================================

class TestBuildScriptContext:
    """事前守护：设定圣经上下文组装。"""

    @pytest.mark.asyncio
    async def test_context_includes_world_setting(self, db_session):
        """上下文包含世界观设定信息。"""
        db_session.add(_make_setting_bible())
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        ctx = await guardian.build_script_context(db_session, 'proj-1')

        assert '修仙大陆' in ctx
        assert '热血' in ctx
        assert '架空古代' in ctx

    @pytest.mark.asyncio
    async def test_context_includes_character_card(self, db_session):
        """上下文包含角色外貌/性格/口癖。"""
        db_session.add(_make_character_card(name='林风'))
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        ctx = await guardian.build_script_context(db_session, 'proj-1')

        assert '林风' in ctx
        assert '黑色长发' in ctx
        assert '红瞳' in ctx
        assert '沉稳冷静' in ctx
        assert '天道不可违' in ctx

    @pytest.mark.asyncio
    async def test_context_includes_previous_episode_summary(self, db_session):
        """上下文包含上一集摘要（前情提要）。"""
        ep1 = ComicEpisode(
            project_id='proj-1', user_id='u-1',
            episode_number=1, title='第一集',
            summary='林风拜入青云宗',
        )
        ep2 = ComicEpisode(
            project_id='proj-1', user_id='u-1',
            episode_number=2, title='第二集',
            summary='第二集内容',
        )
        db_session.add_all([ep1, ep2])
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        # 当前是第二集 → 前情提要应包含第一集摘要
        ctx = await guardian.build_script_context(db_session, 'proj-1', ep2.id)
        assert '林风拜入青云宗' in ctx

    @pytest.mark.asyncio
    async def test_context_empty_when_no_data(self, db_session):
        """无数据时返回空串（降级）。"""
        guardian = ComicConsistencyGuardian()
        ctx = await guardian.build_script_context(db_session, 'proj-nonexistent')
        assert ctx == ''

    @pytest.mark.asyncio
    async def test_context_disabled_returns_empty(self, db_session, monkeypatch):
        """守护未启用时返回空串。"""
        monkeypatch.setattr(
            'app.services.comic.consistency_guardian.pm_feature_config.get_comic_guardian_config',
            lambda: {'enabled': False, 'block_on_critical': True, 'visual_threshold': 0.7},
        )
        db_session.add(_make_character_card())
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        ctx = await guardian.build_script_context(db_session, 'proj-1')
        assert ctx == ''


# =============================================================================
# 测试: gate_transition（事中状态门控）
# =============================================================================

class TestGateTransition:
    """事中守护：镜头状态转换门控。"""

    @pytest.mark.asyncio
    async def test_to_image_pass_when_all_cards_exist(self, db_session):
        """出图前预检：角色卡完整时通过。"""
        db_session.add(_make_character_card(name='林风'))
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, matched_characters=['林风'])
        db_session.add(shot)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_transition(db_session, shot, 'pending_image', 'u-1')

        assert gate.passed is True
        assert gate.blocking is False

    @pytest.mark.asyncio
    async def test_to_image_warns_when_card_missing(self, db_session):
        """出图前预检：缺角色卡时软警告（不阻塞）。"""
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        # 引用一个不存在的角色
        shot = _make_shot(sb.id, matched_characters=['无名氏'])
        db_session.add(shot)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_transition(db_session, shot, 'pending_image', 'u-1')

        assert gate.passed is False
        assert gate.blocking is False  # 软警告，不阻塞
        assert len(gate.issues) == 1
        assert '无名氏' in gate.issues[0].message

    @pytest.mark.asyncio
    async def test_to_video_blocked_when_no_review(self, db_session):
        """视频阶段门控：无审核点时阻塞。"""
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, shot_number=1, status='pending_review_image')
        db_session.add(shot)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_transition(db_session, shot, 'pending_video', 'u-1')

        assert gate.passed is False
        assert gate.blocking is True  # 硬阻塞
        assert any('首帧审核' in i.message for i in gate.issues)

    @pytest.mark.asyncio
    async def test_to_video_blocked_when_review_not_approved(self, db_session):
        """视频阶段门控：审核未通过时阻塞。"""
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, shot_number=1, status='pending_review_image')
        db_session.add(shot)
        await db_session.flush()

        review = ReviewCheckpoint(
            project_id='proj-1', user_id='u-1',
            target_type='shot', target_id=shot.id,
            review_type='first_frame', status='pending',
        )
        db_session.add(review)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_transition(db_session, shot, 'pending_video', 'u-1')

        assert gate.passed is False
        assert gate.blocking is True

    @pytest.mark.asyncio
    async def test_to_video_pass_when_review_approved(self, db_session):
        """视频阶段门控：审核已通过时放行。"""
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, shot_number=1, status='pending_review_image')
        db_session.add(shot)
        await db_session.flush()

        review = ReviewCheckpoint(
            project_id='proj-1', user_id='u-1',
            target_type='shot', target_id=shot.id,
            review_type='first_frame', status='approved',
        )
        db_session.add(review)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_transition(db_session, shot, 'pending_video', 'u-1')

        assert gate.passed is True
        assert gate.blocking is False

    @pytest.mark.asyncio
    async def test_to_review_pass_when_no_asset(self, db_session):
        """审核门控：无图片素材时放行。"""
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, status='pending_image')
        db_session.add(shot)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_transition(db_session, shot, 'pending_review_image', 'u-1')

        assert gate.passed is True

    @pytest.mark.asyncio
    async def test_other_targets_pass(self, db_session):
        """其余状态（pending_voice/pending_composite/completed）放行。"""
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, status='pending_video')
        db_session.add(shot)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        for target in ('pending_voice', 'pending_composite', 'completed'):
            gate = await guardian.gate_transition(db_session, shot, target, 'u-1')
            assert gate.passed is True, f'{target} should pass'


# =============================================================================
# 测试: gate_storyboard_confirm（分镜表批量门控）
# =============================================================================

class TestGateStoryboardConfirm:
    """分镜表确认批量门控。"""

    @pytest.mark.asyncio
    async def test_confirm_passes_when_no_issues(self, db_session):
        """无问题时批量确认通过。"""
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, shot_number=1, dialogue='')
        db_session.add(shot)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_storyboard_confirm(db_session, sb.id, 'proj-1', 'u-1')
        assert gate.passed is True

    @pytest.mark.asyncio
    async def test_confirm_warns_on_missing_cards(self, db_session):
        """缺角色卡时软警告（放行但记录）。"""
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, shot_number=1, matched_characters=['陌生人'])
        db_session.add(shot)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_storyboard_confirm(db_session, sb.id, 'proj-1', 'u-1')

        # 缺角色卡是软警告，不阻塞确认
        assert gate.passed is True
        assert gate.blocking is False
        assert len(gate.issues) >= 1

    @pytest.mark.asyncio
    async def test_confirm_detects_dialogue_style_jump(self, db_session):
        """跨镜对话语气跳变被检测。"""
        db_session.add(_make_character_card(name='老夫'))
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        # 镜头 1：formal 语气
        shot1 = _make_shot(
            sb.id, shot_number=1,
            dialogue='阁下请留步',
            matched_characters=['老夫'],
        )
        # 镜头 2：informal 语气（跳变）
        shot2 = _make_shot(
            sb.id, shot_number=2,
            dialogue='老子要走了',
            matched_characters=['老夫'],
        )
        db_session.add_all([shot1, shot2])
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_storyboard_confirm(db_session, sb.id, 'proj-1', 'u-1')

        # 语气跳变是软警告，放行
        assert gate.passed is True
        # 应检测到对话跳变
        dialogue_issues = [i for i in gate.issues if i.issue_type == 'ca_dialogue_inconsistency']
        assert len(dialogue_issues) >= 1


# =============================================================================
# 测试: GateResult 数据结构
# =============================================================================

class TestGateResult:
    """GateResult 序列化。"""

    def test_to_dict_structure(self):
        from app.services.pm.scanner_base import ScanIssue

        issue = ScanIssue(
            issue_type='test_issue', severity='warning',
            message='测试问题', entities=['shot:1'],
        )
        gate = GateResult(
            passed=False, blocking=True,
            issues=[issue], summary='测试汇总', score=0.65,
        )
        d = gate.to_dict()

        assert d['passed'] is False
        assert d['blocking'] is True
        assert d['summary'] == '测试汇总'
        assert d['score'] == 0.65
        assert len(d['issues']) == 1
        assert d['issues'][0]['type'] == 'test_issue'


# =============================================================================
# 测试: SCAN_REGISTRY 漫剧维度注册
# =============================================================================

class TestComicScannerRegistration:
    """4 个漫剧扫描器通过适配函数注册到 SCAN_REGISTRY。"""

    def test_comic_dimensions_registered(self):
        """注册表包含 4 个漫剧维度。"""
        from app.services.pm.pm_scanners import SCAN_REGISTRY
        expected = {'visual_consistency', 'scene_continuity', 'panel_transition', 'dialogue_bubble'}
        registered = set(SCAN_REGISTRY.keys()) & expected
        assert registered == expected, f'缺少: {expected - registered}'
