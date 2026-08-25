"""pm_fix_handlers / pm_fix_executors 纯函数测试。

覆盖：
- _classify_failure：关键词法环境失败分类
- classify_failure_from_exception：异常类型法分类
- _as_int：稳健转 int（错误兜底回归 bug#3）
- _check_goal_drift：目标偏离检测（章节号正则转义回归 bug#4）
"""
from app.services.pm.pm_fix_handlers import (
    _check_goal_drift,
    _classify_failure,
    classify_failure_from_exception,
)
from app.services.pm.pm_fix_executors import _as_int


class TestClassifyFailure:
    def test_env_keywords(self):
        assert _classify_failure('database connection timeout') == 'env'
        assert _classify_failure('OperationalError: connection pool exhausted') == 'env'
        assert _classify_failure('Connection reset by peer') == 'env'
        assert _classify_failure('SSL handshake failed') == 'env'

    def test_logic_default(self):
        assert _classify_failure('LLM returned invalid JSON') == 'logic'
        assert _classify_failure('角色状态修复失败') == 'logic'

    def test_empty_and_none(self):
        assert _classify_failure('') == 'logic'
        assert _classify_failure(None) == 'logic'


class TestClassifyFailureFromException:
    def test_env_exceptions(self):
        assert classify_failure_from_exception(TimeoutError()) == 'env'
        assert classify_failure_from_exception(ConnectionError()) == 'env'

    def test_message_text_ignored(self):
        # 分类基于异常类型名而非 message：ValueError 类型 → logic
        assert classify_failure_from_exception(ValueError('Connection refused')) == 'logic'

    def test_logic_exceptions(self):
        assert classify_failure_from_exception(ValueError('bad value')) == 'logic'
        assert classify_failure_from_exception(KeyError('x')) == 'logic'


class TestAsInt:
    def test_int_passthrough(self):
        assert _as_int(5) == 5

    def test_numeric_string(self):
        assert _as_int('5') == 5
        assert _as_int('5.7') == 5  # int(float()) 兼容小数

    def test_negative_and_float_string(self):
        assert _as_int('-3') == -3

    def test_invalid_string_uses_default(self):
        assert _as_int('abc') == 0
        assert _as_int('12abc') == 0

    def test_none_uses_default(self):
        assert _as_int(None) == 0

    def test_non_int_types_use_default(self):
        assert _as_int(3.14) == 0   # float 非 int，回退默认
        assert _as_int([1]) == 0

    def test_custom_default(self):
        assert _as_int('abc', default=7) == 7
        assert _as_int(None, default=-1) == -1

    def test_zero_string(self):
        assert _as_int('0') == 0


class TestCheckGoalDrift:
    """目标偏离检测"""

    def test_generic_fix_never_drifts(self):
        assert _check_goal_drift({'repair_intent': 'generic_fix', 'affected_entities': []}, '任意操作') == {
            'drift_score': 0.0,
            'drift_type': 'none',
        }

    def test_entity_overlap_reduces_drift(self):
        # chapter:3 实体 + fix_action 含"第3章" → 实体覆盖 100%，意图匹配 → drift 0
        goal = {'repair_intent': 'fix_character_state', 'affected_entities': ['chapter:3']}
        result = _check_goal_drift(goal, '修正第3章 角色状态')
        assert result == {'drift_score': 0.0, 'drift_type': 'none'}

    def test_chapter_regex_does_not_partial_match(self):
        """回归 bug#4：chapter:3 不应匹配"第30章"（转义 + 边界锚定）"""
        goal = {'repair_intent': 'fix_character_state', 'affected_entities': ['chapter:3']}
        result = _check_goal_drift(goal, '修正第30章 角色状态')
        assert result['drift_score'] > 0.0
        assert result['drift_type'] == 'entity_mismatch'

    def test_missing_entities_affects_drift_score(self):
        goal = {'repair_intent': 'fix_character_state', 'affected_entities': []}
        result = _check_goal_drift(goal, '修正角色状态')
        # intent 匹配成功 → drift = 1 - 0 - 0.3 = 0.7
        assert result['drift_score'] == 0.7
        assert result['drift_type'] == 'entity_mismatch'

    def test_intent_mismatch_raises_drift(self):
        # 实体部分覆盖（chapter:3 命中 → 1/2=0.5）+ 意图不匹配（fix_outline 关键词未命中）
        # drift = 1 - 0.5*0.7 = 0.65 > 0.6，且 overlap≥0.5 → intent_mismatch
        goal = {'repair_intent': 'fix_outline', 'affected_entities': ['chapter:3', 'character:张三']}
        result = _check_goal_drift(goal, '修正第3章 角色状态')
        assert result['drift_score'] == 0.65
        assert result['drift_type'] == 'intent_mismatch'

    def test_mild_drift_stays_none(self):
        # drift ≤ 0.6 不判定为偏离（实现约定：轻微偏离不算偏离）
        goal = {'repair_intent': 'fix_outline', 'affected_entities': ['chapter:3']}
        result = _check_goal_drift(goal, '修正第3章 角色状态')
        assert result['drift_score'] == 0.3
        assert result['drift_type'] == 'none'
