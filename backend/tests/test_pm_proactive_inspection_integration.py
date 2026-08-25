"""pm_proactive_inspector.run_proactive_inspection 集成测试。

sqlite 内存库 + 真实模型写入，验证健康分阈值与建议生成。
只读巡检，无 LLM 依赖。
"""
import uuid

from app.models.chapter import Chapter
from app.models.memory import PlotAnalysis
from app.models.pm_consistency_state import PMConsistencyState
from app.models.pm_v2 import FailurePattern
from app.models.project import Project
from app.services.pm.pm_proactive_inspector import (
    QUALITY_DANGER_THRESHOLD,
    QUALITY_WARNING_THRESHOLD,
    run_proactive_inspection,
)

USER_ID = 'user_inspection'


def _uid() -> str:
    return str(uuid.uuid4())


async def _create_project(db, title='巡检集成项目'):
    p = Project(id=_uid(), user_id=USER_ID, title=title)
    db.add(p)
    await db.commit()
    return p


async def _create_chapter(db, project_id, chapter_number=1, content='测试章节内容'):
    ch = Chapter(
        id=_uid(),
        project_id=project_id,
        chapter_number=chapter_number,
        title=f'第{chapter_number}章',
        content=content,
    )
    db.add(ch)
    await db.commit()
    return ch


class TestRunProactiveInspection:
    async def test_healthy_project(self, db_session):
        """空数据项目 → 健康分 10.0 + 健康建议。"""
        p = await _create_project(db_session)

        report = await run_proactive_inspection(db_session, p.id, USER_ID)
        assert report['overall_health_score'] == 10.0
        assert report['issues'] == []
        assert report['warnings'] == []
        assert any(s['priority'] == 'low' for s in report['suggestions'])

    async def test_low_quality_chapter_critical(self, db_session):
        """PlotAnalysis 评分 < 3.0 → critical issue + 健康分降到 3.0。"""
        p = await _create_project(db_session)
        ch = await _create_chapter(db_session, p.id)
        db_session.add(
            PlotAnalysis(
                id=_uid(),
                project_id=p.id,
                chapter_id=ch.id,
                plot_stage='高潮',
                overall_quality_score=2.0,
                pacing='varied',
                analysis_report='剧情推进生硬，转折缺乏铺垫。',
            )
        )
        await db_session.commit()

        report = await run_proactive_inspection(db_session, p.id, USER_ID)
        assert report['overall_health_score'] == QUALITY_DANGER_THRESHOLD
        assert any(i['type'] == 'low_quality_chapter' and i['severity'] == 'critical' for i in report['issues'])
        assert any(s['priority'] == 'high' for s in report['suggestions'])

    async def test_low_quality_chapter_warning(self, db_session):
        """PlotAnalysis 评分 4.0（<5 但 >=3）→ warning + 健康分降到 5.0。"""
        p = await _create_project(db_session)
        ch = await _create_chapter(db_session, p.id)
        db_session.add(
            PlotAnalysis(
                id=_uid(),
                project_id=p.id,
                chapter_id=ch.id,
                plot_stage='发展',
                overall_quality_score=4.0,
                pacing='slow',
                analysis_report='节奏偏慢。',
            )
        )
        await db_session.commit()

        report = await run_proactive_inspection(db_session, p.id, USER_ID)
        assert report['overall_health_score'] == QUALITY_WARNING_THRESHOLD
        assert any(i['type'] == 'low_quality_chapter' and i['severity'] == 'warning' for i in report['warnings'])

    async def test_failure_pattern_downgrades_score(self, db_session):
        """高频失败模式（occurrence_count>=3）→ warning + 健康分降到 7.0。"""
        p = await _create_project(db_session)
        db_session.add(
            FailurePattern(
                id=_uid(),
                project_id=p.id,
                pattern_type='ooc',
                error_description='角色言行与设定不符',
                root_cause='上下文丢失',
                recovery_suggestion='增加角色卡片上下文',
                occurrence_count=4,
            )
        )
        await db_session.commit()

        report = await run_proactive_inspection(db_session, p.id, USER_ID)
        assert report['overall_health_score'] == 7.0
        assert any(w['type'] == 'failure_pattern' for w in report['warnings'])

    async def test_world_drift_downgrades_score(self, db_session):
        """PMConsistencyState.world_states.drift_detected=True → warning + 健康分降到 8.0。"""
        p = await _create_project(db_session)
        await _create_chapter(db_session, p.id, chapter_number=2)
        await _create_chapter(db_session, p.id, chapter_number=1)
        db_session.add(
            PMConsistencyState(
                id=_uid(),
                project_id=p.id,
                chapter_number=2,
                character_states={},
                world_states={'drift_detected': True, '_world_rules_hash': 'a'},
                foreshadow_status={},
                character_arc_progress={},
            )
        )
        await db_session.commit()

        report = await run_proactive_inspection(db_session, p.id, USER_ID)
        assert report['overall_health_score'] == 8.0
        assert any(w['type'] == 'world_drift' for w in report['warnings'])

    async def test_multiple_issues_min_score(self, db_session):
        """低质量(critical) + 失败模式 + drift 并存 → 健康分取最低 3.0。"""
        p = await _create_project(db_session)
        ch = await _create_chapter(db_session, p.id, chapter_number=1)
        db_session.add(
            PlotAnalysis(
                id=_uid(), project_id=p.id, chapter_id=ch.id, plot_stage='开端',
                overall_quality_score=2.5, pacing='fast', analysis_report='铺垫不足。',
            )
        )
        db_session.add(
            FailurePattern(
                id=_uid(), project_id=p.id, pattern_type='inconsistency',
                error_description='设定前后矛盾', root_cause='大纲未同步',
                recovery_suggestion='修订大纲', occurrence_count=5,
            )
        )
        db_session.add(
            PMConsistencyState(
                id=_uid(), project_id=p.id, chapter_number=1,
                character_states={}, world_states={'drift_detected': True},
                foreshadow_status={}, character_arc_progress={},
            )
        )
        await db_session.commit()

        report = await run_proactive_inspection(db_session, p.id, USER_ID)
        assert report['overall_health_score'] == QUALITY_DANGER_THRESHOLD
        assert len(report['issues']) == 1
        assert len(report['warnings']) == 2
        # 建议应包含低质量 + 失败模式 + 世界观三条
        priorities = {s['priority'] for s in report['suggestions']}
        assert priorities == {'high', 'medium'}

    async def test_project_scope_isolation(self, db_session):
        """项目 A 的低质量数据不影响项目 B 的健康分。"""
        pa = await _create_project(db_session, title='A项目')
        pb = await _create_project(db_session, title='B项目')

        cha = await _create_chapter(db_session, pa.id)
        db_session.add(
            PlotAnalysis(
                id=_uid(), project_id=pa.id, chapter_id=cha.id, plot_stage='开端',
                overall_quality_score=1.0, pacing='fast', analysis_report='较差。',
            )
        )
        await db_session.commit()

        report_a = await run_proactive_inspection(db_session, pa.id, USER_ID)
        report_b = await run_proactive_inspection(db_session, pb.id, USER_ID)
        assert report_a['overall_health_score'] == QUALITY_DANGER_THRESHOLD
        assert report_b['overall_health_score'] == 10.0
        assert report_b['issues'] == []
