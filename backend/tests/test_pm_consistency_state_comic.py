"""PM 漫剧一致性状态快照（PMConsistencyStateComic）单元测试。

覆盖:
- gate 通过后快照写入（pending_image / pending_video）
- 门控失败不写快照
- 同一镜头多次通过 gate → upsert 去重（一镜一条）
- 快照写入异常静默降级（不阻断门控）
"""
import pytest
from app.models.comic_bible import CharacterCard
from app.models.comic_review import ReviewCheckpoint
from app.models.comic_shot import Shot, Storyboard
from app.models.pm_consistency_state_comic import PMConsistencyStateComic
from app.services.comic.consistency_guardian import ComicConsistencyGuardian
from sqlalchemy import select

# =============================================================================
# 辅助工厂
# =============================================================================

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
    matched_characters: list[str] | None = None,
):
    return Shot(
        project_id=project_id,
        user_id=user_id,
        storyboard_id=storyboard_id,
        shot_number=shot_number,
        duration=4.0,
        scene_type='中景',
        visual_description='宗门大殿前',
        character_action='抱拳行礼',
        dialogue='',
        sound_effect='',
        camera_movement='推',
        status=status,
        metadata_json={'matched_characters': matched_characters or []},
    )


def _make_character_card(
    project_id: str = 'proj-1',
    user_id: str = 'u-1',
    name: str = '林风',
):
    return CharacterCard(
        project_id=project_id,
        user_id=user_id,
        name=name,
        hair='黑色长发',
        eyes='红瞳',
        outfit='青色道袍',
        personality='沉稳冷静',
        catchphrase='天道不可违',
    )


# =============================================================================
# 测试: 快照写入
# =============================================================================

class TestSnapshotWrite:
    """gate 通过后写入 PMConsistencyStateComic。"""

    @pytest.mark.asyncio
    async def test_snapshot_written_after_image_gate_pass(self, db_session):
        """pending_image 门控通过 → 写入快照（含角色视觉状态/场景/镜头）。"""
        db_session.add(_make_character_card())
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, matched_characters=['林风'])
        db_session.add(shot)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_transition(db_session, shot, 'pending_image', 'u-1')

        assert gate.passed is True

        snaps = (await db_session.execute(
            select(PMConsistencyStateComic)
        )).scalars().all()
        assert len(snaps) == 1
        snap = snaps[0]
        assert snap.project_id == 'proj-1'
        assert snap.shot_id == shot.id
        assert snap.shot_number == 1
        assert snap.global_sequence == 1
        assert snap.character_visual_states['林风']['appearance'] == '黑色长发，红瞳，青色道袍'
        assert snap.scene_state['scene_type'] == '中景'
        assert snap.camera_state['camera_movement'] == '推'

    @pytest.mark.asyncio
    async def test_snapshot_written_after_video_gate_pass(self, db_session):
        """pending_video 门控通过（首帧已审核）→ 写入快照。"""
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

        snaps = (await db_session.execute(
            select(PMConsistencyStateComic)
        )).scalars().all()
        assert len(snaps) == 1
        assert snaps[0].shot_id == shot.id

    @pytest.mark.asyncio
    async def test_snapshot_not_written_when_gate_blocked(self, db_session):
        """门控阻塞（pending_video 无审核点）→ 不写快照。"""
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, shot_number=1, status='pending_review_image')
        db_session.add(shot)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_transition(db_session, shot, 'pending_video', 'u-1')

        assert gate.passed is False
        assert gate.blocking is True

        snaps = (await db_session.execute(
            select(PMConsistencyStateComic)
        )).scalars().all()
        assert len(snaps) == 0


# =============================================================================
# 测试: upsert 去重
# =============================================================================

class TestSnapshotUpsert:
    """同一镜头多次通过 gate → 一镜一条（更新而非新增）。"""

    @pytest.mark.asyncio
    async def test_same_shot_upsert_single_row(self, db_session):
        """pending_image 通过 + pending_video 通过 → 仍只有 1 条快照。"""
        db_session.add(_make_character_card())
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, matched_characters=['林风'], status='pending_review_image')
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
        gate1 = await guardian.gate_transition(db_session, shot, 'pending_image', 'u-1')
        gate2 = await guardian.gate_transition(db_session, shot, 'pending_video', 'u-1')
        assert gate1.passed is True
        assert gate2.passed is True

        snaps = (await db_session.execute(
            select(PMConsistencyStateComic)
        )).scalars().all()
        assert len(snaps) == 1, '同一镜头应只有一条快照'


# =============================================================================
# 测试: 快照写入异常静默降级
# =============================================================================

class TestSnapshotDegradation:
    """快照写入异常不阻断门控（静默降级）。"""

    @pytest.mark.asyncio
    async def test_snapshot_exception_swallowed(self, db_session, monkeypatch):
        """快照构造/查询异常被吞掉，gate 结果不受影响。"""
        # 用一个构造即抛异常的假类替换模块内 PMConsistencyStateComic
        class _BoomModel:
            def __init__(self, **kwargs):
                raise RuntimeError('boom')

        monkeypatch.setattr(
            'app.services.comic.consistency_guardian.PMConsistencyStateComic',
            _BoomModel,
        )

        db_session.add(_make_character_card())
        sb = _make_storyboard()
        db_session.add(sb)
        await db_session.flush()

        shot = _make_shot(sb.id, matched_characters=['林风'])
        db_session.add(shot)
        await db_session.flush()

        guardian = ComicConsistencyGuardian()
        gate = await guardian.gate_transition(db_session, shot, 'pending_image', 'u-1')

        # 门控仍通过（快照异常不影响）
        assert gate.passed is True