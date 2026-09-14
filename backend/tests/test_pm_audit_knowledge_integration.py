"""PM Agent 红线拦截 / 知识包注入 / 监督层审核 集成测试（Phase 2~4 新增链路）。

覆盖：
1. red_line_check 扫描维度 → issue 携带 red_line_id → _decide_action 强制转人工
2. _execute_and_verify 题材知识包注入（issue['_knowledge_context']）
3. _finalize_decision 将监督层 AuditReport 持久化进 fix_details
4. PMDecisionLog.to_summary 新字段（original_message / audit 摘要等）

依赖：sqlite 内存库 + 真实模型写入（conftest.db_session），无 LLM 依赖。
"""
import json
import uuid

from sqlalchemy import select

from app.models.chapter import Chapter
from app.models.pm_decision_log import PMDecisionLog
from app.models.project import Project
from app.services.pm.pm_agent_decision import _decide_action, _finalize_decision
from app.services.pm.pm_decision_verify import _execute_and_verify
from app.services.pm.pm_scanners import SCAN_REGISTRY

USER_ID = 'user_audit_knowledge'


def _uid() -> str:
    return str(uuid.uuid4())


async def _create_project(db, genre='novel', title='红线集成项目'):
    p = Project(id=_uid(), user_id=USER_ID, title=title, genre=genre)
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


# =============================================================================
# 1. 红线拦截链路
# =============================================================================


class TestRedLineScanAndDecision:
    async def test_red_line_scan_detects_keyword_violation(self, db_session):
        """正文含红线关键词（魔法→RL-002）→ red_line_check 产出带 red_line_id 的 issue。"""
        p = await _create_project(db_session, genre='novel')
        long_content = '夜风呼啸，他抬手施展魔法，火光冲天而起，照亮了整个山谷。' * 3  # >50 字符
        await _create_chapter(db_session, p.id, chapter_number=1, content=long_content)

        scan_fn = SCAN_REGISTRY['red_line_check']['fn']
        issues = await scan_fn(db_session, p.id, USER_ID)

        rl_hits = [i for i in issues if i.get('red_line_id')]
        assert rl_hits, '应至少命中一条红线 issue'
        assert rl_hits[0]['red_line_id'] == 'RL-002'
        assert rl_hits[0]['type'] == 'red_line_violation'
        assert rl_hits[0]['severity'] == 'critical'

    async def test_red_line_issue_forces_manual(self, db_session):
        """带 red_line_id 的 issue → _decide_action 强制转 manual，不尝试修复。"""
        p = await _create_project(db_session)

        issue = {
            'type': 'world_rule_drift',
            'red_line_id': 'RL-002',
            'red_line_name': '世界观规则冲突',
            'severity': 'critical',
            'message': '无魔法世界出现魔法设定',
            'chapter_number': 1,
        }
        result, decision, reason, _lower = await _decide_action(
            db=db_session,
            issue=issue,
            project_id=p.id,
            user_id=USER_ID,
            scan_round='rdl-001',
            total_issues_in_scan=1,
            diag_type='world_rule_drift',
            severity='critical',
            original_message='无魔法世界出现魔法设定',
        )

        assert result is not None
        assert result['decision'] == 'manual'
        assert result['fix_attempted'] is False
        assert result['fix_result'] == 'skipped'
        assert decision == 'manual'
        assert '红线' in reason

        # 决策日志落库（manual，不尝试修复）
        logs = (
            await db_session.execute(
                select(PMDecisionLog).where(
                    PMDecisionLog.project_id == p.id,
                    PMDecisionLog.decision == 'manual',
                )
            )
        ).scalars().all()
        assert logs, '红线拦截应写入 manual 决策日志'
        assert '红线' in (logs[0].decision_reason or '')
        assert logs[0].fix_attempted is False

    async def test_full_scan_to_manual_pipeline(self, db_session):
        """扫描产出红线 issue → 走 _decide_action → manual + 落库 端到端。"""
        p = await _create_project(db_session, genre='novel')
        long_content = '少年身形一晃，瞳色骤然由黑转金，发色亦泛起妖异光芒。' * 2  # 命中 RL-001
        await _create_chapter(db_session, p.id, chapter_number=1, content=long_content)

        scan_fn = SCAN_REGISTRY['red_line_check']['fn']
        issues = await scan_fn(db_session, p.id, USER_ID)
        rl_issue = next((i for i in issues if i.get('red_line_id')), None)
        assert rl_issue is not None, '扫描应命中红线'

        result, decision, reason, _lower = await _decide_action(
            db=db_session,
            issue=rl_issue,
            project_id=p.id,
            user_id=USER_ID,
            scan_round='rdl-002',
            total_issues_in_scan=len(issues),
            diag_type=rl_issue['type'],
            severity=rl_issue['severity'],
            original_message=rl_issue.get('message', ''),
        )
        assert decision == 'manual'
        assert result['fix_attempted'] is False
        assert '红线' in reason

        logs = (
            await db_session.execute(
                select(PMDecisionLog).where(
                    PMDecisionLog.project_id == p.id,
                    PMDecisionLog.diag_type == rl_issue['type'],
                )
            )
        ).scalars().all()
        assert logs and logs[0].decision == 'manual'


# =============================================================================
# 2. 题材知识包注入
# =============================================================================


class TestKnowledgePackInjection:
    async def _run_auto_fix(self, db_session, project_id, issue, monkeypatch):
        """执行一次完整 auto_fix（mock 修复/验证），返回 (issue, exec_state)。

        fake 修复动作需要命中 _check_goal_drift 的意图白名单关键词与 chapter 实体，
        否则 drift_score>0.6 会把 fix_result 降级为 partial（真实链路同此判定）。
        """

        intent_map = {
            'character_consistency': 'fix_character_state',  # 关键词: 角色设定
            'world_rule_drift': 'fix_worldview',  # 关键词: 世界观规则
        }
        intent = intent_map.get(issue.get('type', ''), 'generic_fix')
        ch_num = issue.get('chapter_number') or 1
        if intent == 'fix_worldview':
            fix_text = f'修复完成: 世界观规则已修正（第{ch_num}章）'
        elif intent == 'fix_character_state':
            fix_text = f'修复完成: 角色设定已修正（第{ch_num}章）'
        else:
            fix_text = f'修复完成: 依据题材策略修正设定（第{ch_num}章）'

        async def _fake_execute_fix(_issue, _pid, _uid_, _db):
            return fix_text

        async def _fake_verify_fix(_issue, _pid, _uid_, _db):
            return True, '验证通过'

        monkeypatch.setattr('app.services.pm.pm_decision_verify._execute_fix', _fake_execute_fix)
        monkeypatch.setattr('app.services.pm.pm_decision_verify._verify_fix', _fake_verify_fix)

        original_goal = {
            'repair_intent': intent,
            'affected_entities': [f'chapter:{ch_num}'],
        }
        result, exec_state = await _execute_and_verify(
            db=db_session,
            issue=issue,
            project_id=project_id,
            user_id=USER_ID,
            decision='auto_fix',
            is_lower_risk=False,
            original_goal=original_goal,
            decision_reason='评分达标，执行自动修复',
            diag_type=issue.get('type', ''),
            scan_round='kp-001',
            severity=issue.get('severity', 'warning'),
            original_message=issue.get('message', ''),
        )
        return result, exec_state

    async def test_knowledge_context_injected_for_matched_genre(self, db_session, monkeypatch):
        """genre=仙侠 → auto_fix 前注入题材知识包（theme_id/fix_strategies/readme）。"""
        p = await _create_project(db_session, genre='仙侠', title='知识包注入项目')
        issue = {
            'type': 'character_consistency',
            'severity': 'warning',
            'message': '角色外貌与角色卡不符',
            'chapter_number': 1,
        }

        result, exec_state = await self._run_auto_fix(db_session, p.id, issue, monkeypatch)

        assert result is None  # auto_fix 走执行链，无 early_result
        kp = issue.get('_knowledge_context')
        assert kp, '匹配题材时应注入 _knowledge_context'
        assert kp['genre'] == '仙侠'
        assert kp['theme_id'] == 'xianxia_fantasy'
        assert isinstance(kp['fix_strategies'], list)
        assert kp['readme_excerpt'], 'readme 摘录不应为空'
        assert exec_state['fix_result'] == 'success'

    async def test_no_injection_without_genre_match(self, db_session, monkeypatch):
        """genre=novel（无题材映射）→ 不注入 _knowledge_context，修复链不受影响。"""
        p = await _create_project(db_session, genre='novel')
        issue = {
            'type': 'character_consistency',
            'severity': 'warning',
            'message': '角色外貌与角色卡不符',
            'chapter_number': 1,
        }

        result, exec_state = await self._run_auto_fix(db_session, p.id, issue, monkeypatch)

        assert result is None
        assert '_knowledge_context' not in issue
        assert exec_state['fix_result'] == 'success'

    async def test_injection_for_english_genre_keyword(self, db_session, monkeypatch):
        """genre=都市 → 映射 urban_workplace 题材包注入。"""
        p = await _create_project(db_session, genre='都市')
        issue = {
            'type': 'world_rule_drift',
            'severity': 'warning',
            'message': '世界观规则前后矛盾',
            'chapter_number': 1,
        }

        result, exec_state = await self._run_auto_fix(db_session, p.id, issue, monkeypatch)

        assert result is None
        kp = issue.get('_knowledge_context')
        assert kp and kp['theme_id'] == 'urban_workplace'
        assert exec_state['fix_result'] == 'success'


# =============================================================================
# 3. AuditReport 持久化
# =============================================================================


class TestAuditReportPersistence:
    def _audit_report(self):
        return {
            'score': 'B',
            'summary': '修复结果审核',
            'passed': True,
            'issues': [],
        }

    def _exec_state(self, **overrides):
        state = {
            'fix_action': '修复完成: 修正角色外貌',
            'fix_result': 'success',
            'fix_attempted': True,
            'verified': True,
            'verified_at': None,
            'verify_message': '验证通过',
            'drift_result': {'drift_score': 0, 'drift_type': ''},
            'audit_report': None,
        }
        state.update(overrides)
        return state

    async def test_audit_report_persisted_into_fix_details(self, db_session):
        """exec_state 携带 audit_report → _finalize_decision 写入 fix_details JSON。"""
        p = await _create_project(db_session)
        issue = {
            'type': 'character_consistency',
            'severity': 'warning',
            'message': '角色外貌与角色卡不符',
            'chapter_number': 1,
        }
        audit = self._audit_report()
        exec_state = self._exec_state(audit_report=audit)

        result = await _finalize_decision(
            db=db_session,
            issue=issue,
            project_id=p.id,
            user_id=USER_ID,
            scan_round='ar-001',
            diag_type='character_consistency',
            severity='warning',
            original_message='角色外貌与角色卡不符',
            decision='auto_fix',
            decision_reason='评分达标',
            exec_state=exec_state,
            goal_id=_uid(),
            original_goal={'repair_intent': '修正角色外貌'},
        )

        assert result['decision_log_id'] is not None
        log = (
            await db_session.execute(
                select(PMDecisionLog).where(PMDecisionLog.id == result['decision_log_id'])
            )
        ).scalar_one()
        details = json.loads(log.fix_details)
        assert details['audit_report'] == audit

        # to_summary 的 audit 摘要应能解析出来
        summary = log.to_summary()
        assert summary['audit']['score'] == 'B'
        assert summary['audit']['passed'] is True
        assert summary['audit']['issue_count'] == 0

    async def test_no_audit_report_when_exec_state_empty(self, db_session):
        """exec_state 无 audit_report → fix_details 不含该键（向后兼容）。"""
        p = await _create_project(db_session)
        issue = {
            'type': 'character_consistency',
            'severity': 'warning',
            'message': '角色外貌与角色卡不符',
            'chapter_number': 1,
        }
        exec_state = self._exec_state()  # audit_report=None

        result = await _finalize_decision(
            db=db_session,
            issue=issue,
            project_id=p.id,
            user_id=USER_ID,
            scan_round='ar-002',
            diag_type='character_consistency',
            severity='warning',
            original_message='角色外貌与角色卡不符',
            decision='auto_fix',
            decision_reason='评分达标',
            exec_state=exec_state,
            goal_id=_uid(),
            original_goal={'repair_intent': '修正角色外貌'},
        )

        log = (
            await db_session.execute(
                select(PMDecisionLog).where(PMDecisionLog.id == result['decision_log_id'])
            )
        ).scalar_one()
        details = json.loads(log.fix_details)
        assert 'audit_report' not in details
        assert log.to_summary()['audit'] is None


# =============================================================================
# 4. to_summary 新字段
# =============================================================================


class TestToSummaryFields:
    def test_summary_includes_phase42_fields(self):
        """to_summary 补齐 original_message/decision_reason/verify_message/fix_attempted 等。"""
        log = PMDecisionLog(
            id='d1',
            project_id='p1',
            user_id='u1',
            diag_type='world_rule_drift',
            chapter_number=1,
            severity='critical',
            original_message='无魔法世界出现魔法设定',
            decision='manual',
            decision_reason='命中红线 RL-002',
            verify_message='等待人工处理',
            fix_attempted=False,
            fix_result='skipped',
            verified=False,
        )
        s = log.to_summary()
        assert s['original_message'] == '无魔法世界出现魔法设定'
        assert s['decision_reason'] == '命中红线 RL-002'
        assert s['verify_message'] == '等待人工处理'
        assert s['fix_attempted'] is False
        assert s['user_feedback'] is None
        assert s['feedback_note'] == ''

    def test_audit_summary_parsed_from_fix_details(self):
        """fix_details 含 audit_report → audit 摘要带 score/passed/has_red_line。"""
        log = PMDecisionLog(
            id='d2',
            project_id='p1',
            user_id='u1',
            diag_type='world_rule_drift',
            fix_details=json.dumps(
                {
                    'fix_result_detail': '',
                    'audit_report': {
                        'score': 'D',
                        'summary': '命中红线 RL-002，转人工处理',
                        'passed': False,
                        'issues': [
                            {
                                'severity': 'critical',
                                'check_item': 'red_line_violation',
                                'problem': '命中红线规则 RL-002',
                                'suggestion': '转人工',
                                'red_line_id': 'RL-002',
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            ),
        )
        audit = log._extract_audit_summary()
        assert audit['score'] == 'D'
        assert audit['passed'] is False
        assert audit['has_red_line'] is True
        assert audit['issue_count'] == 1
        assert log.to_summary()['audit'] == audit

    def test_audit_none_when_fix_details_corrupt(self):
        """fix_details 为坏 JSON → audit=None 不抛异常。"""
        log = PMDecisionLog(id='d3', fix_details='{not valid json')
        s = log.to_summary()
        assert s['audit'] is None

    def test_audit_none_without_audit_report(self):
        """fix_details 无 audit_report 键 → audit=None。"""
        log = PMDecisionLog(id='d4', fix_details='{"fix_result_detail": "ok"}')
        assert log._extract_audit_summary() is None

    def test_audit_has_red_line_false_when_no_red_line_issues(self):
        """audit issues 无 red_line_id → has_red_line=False。"""
        log = PMDecisionLog(
            id='d5',
            fix_details=json.dumps(
                {
                    'audit_report': {
                        'score': 'B',
                        'summary': '通过',
                        'passed': True,
                        'issues': [
                            {
                                'severity': 'warning',
                                'check_item': 'info_completeness',
                                'problem': '缺章节号',
                                'suggestion': '补章节号',
                            }
                        ],
                    }
                },
                ensure_ascii=False,
            ),
        )
        audit = log._extract_audit_summary()
        assert audit['has_red_line'] is False
        assert audit['issue_count'] == 1