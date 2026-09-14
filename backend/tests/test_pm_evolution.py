"""PM 自进化引擎单元测试 — 信号聚合/阈值进化/排除规则/维度节流。

覆盖 pm_evolution.py 的核心决策逻辑（不依赖 LLM，纯 DB + 规则）。
"""
import asyncio
import uuid
from datetime import datetime, timedelta

import pytest

from app.models.pm_decision_log import PMDecisionLog
from app.services.pm.pm_evolution import (
    _aggregate_signals,
    _adjust_throttle,
    _evolve_threshold,
    _extract_exclusion_key,
    _param_bounds,
    _rule_matches,
    evolve_after_round,
    filter_exclusions,
    is_evolution_enabled,
    learn_from_rejection,
)


def _mk_decision(project_id: str, diag_type: str, **kw) -> PMDecisionLog:
    return PMDecisionLog(
        id=str(uuid.uuid4()),
        project_id=project_id,
        diag_type=diag_type,
        original_message=kw.pop('original_message', ''),
        chapter_number=kw.pop('chapter_number', None),
        fix_result=kw.pop('fix_result', 'skipped'),
        verified=kw.pop('verified', False),
        user_feedback=kw.pop('user_feedback', None),
        created_at=kw.pop('created_at', datetime.now()),
    )


class TestIsEnabled:
    def test_enabled(self):
        # pm_features.yaml 已开启 self_evolution
        assert is_evolution_enabled() is True


class TestAggregateSignals:
    async def test_no_signals(self, db_session):
        signals = await _aggregate_signals(db_session, 'proj-a', 'character_consistency')
        assert signals['total'] == 0
        assert signals['fix_rate'] == 0.5
        assert signals['fp_rate'] == 0.0

    async def test_signals_aggregated(self, db_session):
        pid = 'proj-b'
        for i in range(3):
            db_session.add(_mk_decision(pid, 'pm_agent_character_jump', fix_result='success'))
        db_session.add(_mk_decision(pid, 'pm_agent_character_jump', user_feedback='rejected'))
        await db_session.commit()
        signals = await _aggregate_signals(db_session, pid, 'character_consistency')
        assert signals['total'] == 4
        assert signals['hits'] == 3
        assert signals['fp'] == 1


class TestEvolveThreshold:
    async def test_no_trigger_when_healthy(self, db_session):
        from app.services.pm.pm_evolution import PMEvolutionState

        st = PMEvolutionState(project_id='p', dimension='character_consistency')
        db_session.add(st)
        await db_session.commit()
        # 修复率健康，误报 0 → 不应触发变更
        changed = _evolve_threshold(
            db_session, st,
            {'total': 10, 'fp_rate': 0.0, 'fix_rate': 0.9},
            default=3.0, lo=1.0, hi=5.0,
        )
        assert changed is False
        assert st.threshold_value is None

    async def test_high_fp_triggers_desensitize(self, db_session):
        from app.services.pm.pm_evolution import PMEvolutionState

        st = PMEvolutionState(project_id='p', dimension='character_consistency')
        db_session.add(st)
        await db_session.commit()
        # z_score_threshold sensitivity=-1，误报高 → 阈值调高（降敏感）
        changed = _evolve_threshold(
            db_session, st,
            {'total': 6, 'fp_rate': 0.8, 'fix_rate': 0.3},
            default=3.0, lo=1.0, hi=5.0,
        )
        assert changed is True
        assert st.threshold_value > 3.0
        assert st.status == 'evolving'
        assert st.threshold_original == 3.0

    async def test_bounds_respected(self, db_session):
        from app.services.pm.pm_evolution import PMEvolutionState

        st = PMEvolutionState(project_id='p', dimension='character_consistency')
        db_session.add(st)
        await db_session.commit()
        for _ in range(10):
            _evolve_threshold(
                db_session, st,
                {'total': 6, 'fp_rate': 0.9, 'fix_rate': 0.1},
                default=3.0, lo=1.0, hi=5.0,
            )
        assert st.threshold_value <= 5.0

    async def test_low_confidence_pauses(self, db_session):
        from app.services.pm.pm_evolution import PMEvolutionState

        st = PMEvolutionState(project_id='p', dimension='character_consistency', confidence=0.1)
        db_session.add(st)
        await db_session.commit()
        changed = _evolve_threshold(
            db_session, st,
            {'total': 6, 'fp_rate': 0.8, 'fix_rate': 0.2},
            default=3.0, lo=1.0, hi=5.0,
        )
        assert changed is False


class TestThrottle:
    async def test_clean_rounds_accumulate(self, db_session):
        from app.services.pm.pm_evolution import PMEvolutionState, THROTTLE_AFTER_CLEAN

        st = PMEvolutionState(project_id='p', dimension='quality_score')
        db_session.add(st)
        await db_session.commit()
        for _ in range(THROTTLE_AFTER_CLEAN):
            await _adjust_throttle(db_session, st, 0)
        assert st.status == 'throttled'
        assert st.throttle_until is not None

    async def test_issue_resets_throttle(self, db_session):
        from app.services.pm.pm_evolution import PMEvolutionState, THROTTLE_AFTER_CLEAN

        st = PMEvolutionState(project_id='p', dimension='quality_score')
        db_session.add(st)
        await db_session.commit()
        for _ in range(THROTTLE_AFTER_CLEAN):
            await _adjust_throttle(db_session, st, 0)
        assert st.status == 'throttled'
        await _adjust_throttle(db_session, st, 2)
        assert st.status == 'stable'
        assert st.consecutive_clean_rounds == 0


class TestExclusionLearning:
    def test_extract_character(self):
        assert _extract_exclusion_key('pm_agent_character_jump', '角色 张三 位置跳变', None) == ('character', '张三')

    def test_extract_foreshadow(self):
        assert _extract_exclusion_key('pm_agent_foreshadow_stale', '伏笔「神秘玉佩」', None) == ('foreshadow', '神秘玉佩')

    def test_extract_chapter(self):
        assert _extract_exclusion_key('pm_agent_quality_score_low', '质量低', 12) == ('chapter', '12')

    def test_extract_unsupported(self):
        assert _extract_exclusion_key('pm_agent_world_drift', '世界观漂移', 1) == (None, None)

    async def test_learn_from_rejection_creates_rule(self, db_session):
        log = _mk_decision(
            'proj-c', 'pm_agent_character_jump',
            original_message='角色 李四 位置跳变', chapter_number=3,
        )
        db_session.add(log)
        await db_session.commit()
        rule = await learn_from_rejection(db_session, log)
        assert rule is not None
        assert rule.rule_type == 'character'
        assert rule.rule_key == '李四'
        assert rule.enabled is True

    async def test_learn_deduplicates(self, db_session):
        log = _mk_decision(
            'proj-c', 'pm_agent_character_jump',
            original_message='角色 李四 位置跳变', chapter_number=3,
        )
        db_session.add(log)
        await db_session.commit()
        r1 = await learn_from_rejection(db_session, log)
        r2 = await learn_from_rejection(db_session, log)
        assert r1.id == r2.id


class TestRuleMatching:
    def test_character_match(self):
        from app.models.pm_evolution import PMExclusionRule

        rule = PMExclusionRule(project_id='p', dimension='d', rule_type='character', rule_key='张三')
        assert _rule_matches(rule, {'character': '张三'}) is True
        assert _rule_matches(rule, {'character': '李四'}) is False

    def test_foreshadow_match(self):
        from app.models.pm_evolution import PMExclusionRule

        rule = PMExclusionRule(project_id='p', dimension='d', rule_type='foreshadow', rule_key='玉佩')
        assert _rule_matches(rule, {'title': '玉佩'}) is True
        assert _rule_matches(rule, {'title': '剑'}) is False

    def test_chapter_match_variants(self):
        from app.models.pm_evolution import PMExclusionRule

        rule = PMExclusionRule(project_id='p', dimension='d', rule_type='chapter', rule_key='12')
        assert _rule_matches(rule, {'chapter': 12}) is True
        assert _rule_matches(rule, {'chapter_number': '12'}) is True
        assert _rule_matches(rule, {'planted_chapter': 12}) is True
        assert _rule_matches(rule, {'chapter': 13}) is False


class TestFilterExclusions:
    async def test_filters_and_counts_hits(self, db_session):
        from app.models.pm_evolution import PMExclusionRule

        db_session.add(PMExclusionRule(project_id='p', dimension='character_consistency', rule_type='character', rule_key='张三'))
        await db_session.commit()
        issues = [{'character': '张三'}, {'character': '李四'}, {'character': '王五'}]
        kept = await filter_exclusions(db_session, 'p', 'character_consistency', issues)
        assert len(kept) == 2
        rule = (await db_session.execute(
            __import__('sqlalchemy').select(PMExclusionRule)
        )).scalar_one()
        assert rule.hits == 1

    async def test_no_rules_passes_through(self, db_session):
        issues = [{'character': '张三'}]
        kept = await filter_exclusions(db_session, 'p', 'character_consistency', issues)
        assert kept == issues


class TestParamBounds:
    def test_bounds_readable(self):
        default, lo, hi = _param_bounds('character_consistency', 'z_score_threshold')
        assert default is not None
        assert lo is not None and hi is not None
        assert lo <= default <= hi
