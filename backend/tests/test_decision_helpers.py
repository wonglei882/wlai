"""pm_decision_helpers 纯函数测试。

覆盖：
- _rule_based_sort：severity/type/chapter 三级排序 + type 精确匹配回归（bug#2）
- _compute_decision_score：决策分阈值边界 + 上下界 clamp + 不确定性惩罚
- _decompose_repair_priority：短列表分支（≤3 不触 DB/AI）
"""
import asyncio

from app.services.pm.pm_decision_helpers import (
    _compute_decision_score,
    _decompose_repair_priority,
    _rule_based_sort,
)


class TestRuleBasedSort:
    """排序规则：severity > type > chapter"""

    def test_severity_order(self):
        issues = [
            {'type': 'outline', 'severity': 'warning', 'chapter': 5},
            {'type': 'character', 'severity': 'info', 'chapter': 1},
            {'type': 'foreshadow', 'severity': 'critical', 'chapter': 3},
        ]
        result = _rule_based_sort(issues)
        assert [i['severity'] for i in result] == ['critical', 'warning', 'info']
        assert result[0]['type'] == 'foreshadow'

    def test_type_order_within_same_severity(self):
        issues = [
            {'type': 'quality', 'severity': 'critical', 'chapter': 1},
            {'type': 'character', 'severity': 'critical', 'chapter': 1},
            {'type': 'world', 'severity': 'critical', 'chapter': 1},
        ]
        result = _rule_based_sort(issues)
        assert [i['type'] for i in result] == ['character', 'world', 'quality']

    def test_chapter_ascending(self):
        issues = [
            {'type': 'character', 'severity': 'critical', 'chapter': 5},
            {'type': 'character', 'severity': 'critical', 'chapter': 3},
            {'type': 'character', 'severity': 'critical', 'chapter': 8},
        ]
        result = _rule_based_sort(issues)
        assert [i['chapter'] for i in result] == [3, 5, 8]

    def test_string_chapter_coerced_to_int(self):
        issues = [
            {'type': 'character', 'severity': 'critical', 'chapter': '5'},
            {'type': 'character', 'severity': 'critical', 'chapter': '3'},
        ]
        result = _rule_based_sort(issues)
        assert [i['chapter'] for i in result] == ['3', '5']

    def test_invalid_chapter_sorts_last(self):
        issues = [
            {'type': 'character', 'severity': 'critical', 'chapter': 1},
            {'type': 'character', 'severity': 'critical', 'chapter': 'unknown'},
            {'type': 'character', 'severity': 'critical', 'chapter': 2},
        ]
        result = _rule_based_sort(issues)
        assert [i['chapter'] for i in result] == [1, 2, 'unknown']

    def test_type_exact_match_regression(self):
        """回归 bug#2：子串匹配会把 character_location_jump 误判为 character。

        精确匹配下 character_location_jump 的 type 优先级为默认值 5，
        必须排在 character（优先级 0）之后。
        """
        issues = [
            {'type': 'character_location_jump', 'severity': 'critical', 'chapter': 1},
            {'type': 'character', 'severity': 'critical', 'chapter': 1},
        ]
        result = _rule_based_sort(issues)
        assert result[0]['type'] == 'character'
        assert result[1]['type'] == 'character_location_jump'

    def test_missing_fields_use_defaults(self):
        issues = [
            {'severity': 'warning'},                      # 无 type/chapter
            {'type': 'character'},                        # 无 severity/chapter
            {'type': 'worldview', 'severity': 'info'},
        ]
        result = _rule_based_sort(issues)                 # 不应抛异常
        assert len(result) == 3


class TestComputeDecisionScore:
    """决策分阈值：≥0.50 auto_fix | 0.30~0.49 auto_fix(低风险) | <0.30 manual"""

    def test_high_benefit_low_risk_is_auto_fix(self):
        score = _compute_decision_score(severity_val=1.0, success_rate=0.9, cooldown_penalty=0.0, issue_confidence=1.0)
        assert score >= 0.50

    def test_mid_zone(self):
        score = _compute_decision_score(severity_val=0.6, success_rate=0.8, cooldown_penalty=0.1)
        assert 0.30 <= score < 0.50

    def test_low_score_is_manual(self):
        score = _compute_decision_score(severity_val=0.2, success_rate=0.1, cooldown_penalty=0.8)
        assert score < 0.30

    def test_upper_clamp(self):
        score = _compute_decision_score(severity_val=1.0, success_rate=1.0, cooldown_penalty=0.0, issue_confidence=1.0)
        assert score <= 1.0

    def test_lower_clamp(self):
        score = _compute_decision_score(severity_val=0.0, success_rate=0.0, cooldown_penalty=1.0)
        assert score >= -0.5

    def test_uncertainty_penalty_lowers_score(self):
        base = _compute_decision_score(severity_val=0.6, success_rate=0.6, cooldown_penalty=0.2)
        penalized = _compute_decision_score(
            severity_val=0.6, success_rate=0.6, cooldown_penalty=0.2, uncertainty_penalty=0.3
        )
        assert penalized < base

    def test_effective_rate_never_negative(self):
        # uncertainty 超过 success_rate 时，有效成功率钳制为 0，不会出现负收益
        # benefit = 1.0(severity) * 0.8(默认 confidence) * (0.5 + 0.0) = 0.4
        score = _compute_decision_score(
            severity_val=1.0, success_rate=0.1, cooldown_penalty=0.0, uncertainty_penalty=0.5
        )
        assert score == 0.4


class TestDecomposeRepairPriority:
    """短列表分支：问题数 ≤3 时直接返回，不触 DB/AI"""

    def test_short_list_returns_early(self):
        issues = [
            {'type': 'character', 'severity': 'critical'},
            {'type': 'outline', 'severity': 'warning'},
            {'type': 'foreshadow', 'severity': 'info'},
        ]
        # db 传 None：若误触 DB 会立即抛 AttributeError，从而验证分支短路
        result, reasoning = asyncio.run(_decompose_repair_priority(None, issues, 'proj-x', 'user-y'))
        assert result == issues
        assert '无需分解' in reasoning

    def test_single_issue_returns_early(self):
        issues = [{'type': 'character', 'severity': 'critical'}]
        result, reasoning = asyncio.run(_decompose_repair_priority(None, issues, 'proj-x', 'user-y'))
        assert result == issues
        assert '无需分解' in reasoning
