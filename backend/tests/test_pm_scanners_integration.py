"""pm_scanners 集成测试 — sqlite 内存库 + 真实模型写入后扫描。

覆盖（无 LLM 依赖的纯查库维度）：
- _scan_character_consistency：相邻章角色位置跳变（硬阈值分支）
- _scan_foreshadow_age：planted 超龄伏笔
- _scan_world_rule_drift：相邻章世界观 hash 漂移（diff_rate > 0.5）
- _scan_paragraph_format：超长段落章节
- _write_diagnostic_from_scan：诊断日志 upsert 写入
"""
import uuid

from sqlalchemy import select

from app.models.chapter import Chapter
from app.models.foreshadow import Foreshadow
from app.models.pm_consistency_state import PMConsistencyState
from app.models.pm_diagnostic_log import PMDiagnosticLog
from app.models.project import Project
from app.services.pm.pm_scanners import (
    _scan_character_consistency,
    _scan_foreshadow_age,
    _scan_paragraph_format,
    _scan_world_rule_drift,
    _write_diagnostic_from_scan,
)

USER_ID = 'user_integration'


def _uid() -> str:
    return str(uuid.uuid4())


async def _create_project(db, title='集成测试项目'):
    p = Project(id=_uid(), user_id=USER_ID, title=title)
    db.add(p)
    await db.commit()
    return p


async def _create_chapter(db, project_id, chapter_number, content=None):
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


class TestScanCharacterConsistency:
    async def test_adjacent_chapter_jump_detected(self, db_session):
        """样本 <5 走硬阈值：相邻章同一角色 location 不同 → issue。"""
        p = await _create_project(db_session)
        await _create_chapter(db_session, p.id, 2)
        await _create_chapter(db_session, p.id, 1)
        db_session.add_all(
            [
                PMConsistencyState(
                    id=_uid(), project_id=p.id, chapter_number=2,
                    character_states={'阿铁': {'location': '阴司', 'emotion': '平静'}},
                    world_states={}, foreshadow_status={}, character_arc_progress={},
                ),
                PMConsistencyState(
                    id=_uid(), project_id=p.id, chapter_number=1,
                    character_states={'阿铁': {'location': '阳间', 'emotion': '焦虑'}},
                    world_states={}, foreshadow_status={}, character_arc_progress={},
                ),
            ]
        )
        await db_session.commit()

        issues = await _scan_character_consistency(db_session, p.id, USER_ID)
        assert issues, '相邻章角色位置跳变应产出 issue'
        assert issues[0]['type'] == 'character_location_jump'
        assert issues[0]['character'] == '阿铁'
        assert issues[0]['from'] == '阴司'
        assert issues[0]['to'] == '阳间'
        assert issues[0]['detection'] == 'hard_threshold'

    async def test_no_jump_no_issue(self, db_session):
        """相邻章 location 相同 → 无 issue。"""
        p = await _create_project(db_session)
        await _create_chapter(db_session, p.id, 2)
        await _create_chapter(db_session, p.id, 1)
        db_session.add_all(
            [
                PMConsistencyState(
                    id=_uid(), project_id=p.id, chapter_number=2,
                    character_states={'阿铁': {'location': '阴司'}},
                    world_states={}, foreshadow_status={}, character_arc_progress={},
                ),
                PMConsistencyState(
                    id=_uid(), project_id=p.id, chapter_number=1,
                    character_states={'阿铁': {'location': '阴司'}},
                    world_states={}, foreshadow_status={}, character_arc_progress={},
                ),
            ]
        )
        await db_session.commit()

        issues = await _scan_character_consistency(db_session, p.id, USER_ID)
        assert issues == []


class TestScanForeshadowAge:
    async def test_aged_planted_foreshadow_detected(self, db_session):
        """最新章 15，第 1 章埋下仍未解决（age=14，urgency≈0.81）→ issue。"""
        p = await _create_project(db_session)
        await _create_chapter(db_session, p.id, 15)
        db_session.add(
            Foreshadow(
                id=_uid(), project_id=p.id, title='铜钥匙', content='某处的铜钥匙',
                status='planted', plant_chapter_number=1, category='identity',
            )
        )
        await db_session.commit()

        issues = await _scan_foreshadow_age(db_session, p.id, USER_ID)
        assert issues, 'planted 超龄伏笔应产出 issue'
        issue = issues[0]
        assert issue['type'] == 'foreshadow_stale'
        assert issue['title'] == '铜钥匙'
        assert issue['age'] == 14
        assert issue['urgency_score'] > 0.5

    async def test_fresh_foreshadow_no_issue(self, db_session):
        """最新章 15，第 14 章刚埋下（age=1，urgency 低）→ 无 issue。"""
        p = await _create_project(db_session)
        await _create_chapter(db_session, p.id, 15)
        db_session.add(
            Foreshadow(
                id=_uid(), project_id=p.id, title='新伏笔', content='刚埋下',
                status='planted', plant_chapter_number=14, category='identity',
            )
        )
        await db_session.commit()

        issues = await _scan_foreshadow_age(db_session, p.id, USER_ID)
        assert issues == []


class TestScanWorldRuleDrift:
    async def test_hash_drift_above_threshold_detected(self, db_session):
        """相邻章 world hash 不同且规则差异率 100% > 50% → issue。"""
        p = await _create_project(db_session)
        await _create_chapter(db_session, p.id, 2)
        await _create_chapter(db_session, p.id, 1)
        db_session.add_all(
            [
                PMConsistencyState(
                    id=_uid(), project_id=p.id, chapter_number=2,
                    character_states={},
                    world_states={'_world_rules_hash': 'hash_aaa', '_appeared_rules': ['规则A', '规则B']},
                    foreshadow_status={}, character_arc_progress={},
                ),
                PMConsistencyState(
                    id=_uid(), project_id=p.id, chapter_number=1,
                    character_states={},
                    world_states={'_world_rules_hash': 'hash_bbb', '_appeared_rules': ['规则C', '规则D']},
                    foreshadow_status={}, character_arc_progress={},
                ),
            ]
        )
        await db_session.commit()

        issues = await _scan_world_rule_drift(db_session, p.id, USER_ID)
        assert issues, 'hash 不同且差异率>50% 应产出 issue'
        assert issues[0]['type'] == 'world_rule_drift'
        assert issues[0]['diff_rate'] == 1.0

    async def test_same_hash_no_issue(self, db_session):
        """相邻章 world hash 相同 → 无 issue。"""
        p = await _create_project(db_session)
        await _create_chapter(db_session, p.id, 2)
        await _create_chapter(db_session, p.id, 1)
        db_session.add_all(
            [
                PMConsistencyState(
                    id=_uid(), project_id=p.id, chapter_number=2,
                    character_states={},
                    world_states={'_world_rules_hash': 'same', '_appeared_rules': ['规则A']},
                    foreshadow_status={}, character_arc_progress={},
                ),
                PMConsistencyState(
                    id=_uid(), project_id=p.id, chapter_number=1,
                    character_states={},
                    world_states={'_world_rules_hash': 'same', '_appeared_rules': ['规则A']},
                    foreshadow_status={}, character_arc_progress={},
                ),
            ]
        )
        await db_session.commit()

        issues = await _scan_world_rule_drift(db_session, p.id, USER_ID)
        assert issues == []


class TestScanParagraphFormat:
    async def test_long_paragraphs_detected(self, db_session):
        """章节含 4 个 150 字段落（>110 且 >3 个）→ issue。"""
        long_para = '长' * 150
        content = '\n\n'.join([long_para, long_para, long_para, long_para, '短段落'])
        p = await _create_project(db_session)
        await _create_chapter(db_session, p.id, 1, content=content)

        issues = await _scan_paragraph_format(db_session, p.id, USER_ID)
        assert issues, '超长段落应产出 issue'
        issue = issues[0]
        assert issue['type'] == 'paragraph_too_long'
        assert issue['long_para_count'] == 4
        assert issue['total_paras'] == 5

    async def test_normal_paragraphs_no_issue(self, db_session):
        """章节段落均在 110 字内 → 无 issue。"""
        para = '短' * 60
        content = '\n\n'.join([para, para, para, para])
        p = await _create_project(db_session)
        await _create_chapter(db_session, p.id, 1, content=content)

        issues = await _scan_paragraph_format(db_session, p.id, USER_ID)
        assert issues == []


class TestWriteDiagnosticFromScan:
    async def test_write_and_upsert(self, db_session):
        """同类型同章节诊断 → upsert 为一条且更新 message。"""
        p = await _create_project(db_session)
        await _create_chapter(db_session, p.id, 3)

        await _write_diagnostic_from_scan(
            db_session, p.id, USER_ID, 'pm_agent_paragraph_too_long',
            chapter_number=3, message='超长段落', details={'count': 4},
        )
        await _write_diagnostic_from_scan(
            db_session, p.id, USER_ID, 'pm_agent_paragraph_too_long',
            chapter_number=3, message='超长段落(更新)', details={'count': 5},
        )

        result = await db_session.execute(
            select(PMDiagnosticLog).where(PMDiagnosticLog.project_id == p.id)
        )
        logs = result.scalars().all()
        assert len(logs) == 1, '同类型诊断应 upsert 为一条'
        assert logs[0].message == '超长段落(更新)'
        assert logs[0].severity == 'warning'
        assert logs[0].resolved is False
