"""quality_scorer 纯函数测试。

覆盖：
- total_score：加权总分 + 自定义权重归一化
- 三个密度指标：因果密度 / 冲突烈度 / 伏笔密度
- 规则评分 fallback（ai_service=None 时不触 AI/DB）
- ScoreResult.failed_dimensions
- _build_improvement_hints
- QualityLoop.MAX_RETRIES 存在性回归（bug#1）
"""
import asyncio

import pytest

from app.services.pm.quality_scorer import PMQualityScorerV2, QualityLoop, ScoreResult

DEFAULT_DIMENSIONS = PMQualityScorerV2.DEFAULT_DIMENSIONS


class TestTotalScore:
    def test_weights_sum_to_one(self):
        assert abs(sum(DEFAULT_DIMENSIONS.values()) - 1.0) < 1e-9

    def test_perfect_score(self):
        scorer = PMQualityScorerV2()
        scores = {dim: 100 for dim in DEFAULT_DIMENSIONS}
        assert scorer.total_score(scores) == 100.0

    def test_uniform_60(self):
        scorer = PMQualityScorerV2()
        scores = {dim: 60 for dim in DEFAULT_DIMENSIONS}
        assert scorer.total_score(scores) == 60.0

    def test_empty_scores(self):
        scorer = PMQualityScorerV2()
        assert scorer.total_score({}) == 0.0

    def test_missing_dimension_treated_as_zero(self):
        scorer = PMQualityScorerV2()
        scores = {'pacing': 100}
        expected = 100 * DEFAULT_DIMENSIONS['pacing']  # 其余维度按 0
        assert scorer.total_score(scores) == expected

    def test_custom_weights_normalized(self):
        # 自定义权重和≠1 时仍应归一化，比较基准不变
        scorer = PMQualityScorerV2(weights={'a': 1, 'b': 3})
        assert scorer.total_score({'a': 100, 'b': 0}) == 25.0
        assert scorer.total_score({'a': 0, 'b': 100}) == 75.0

    def test_instance_weights_fallback_to_defaults(self):
        scorer = PMQualityScorerV2()
        assert scorer.DIMENSIONS == DEFAULT_DIMENSIONS


class TestDensityMetrics:
    def test_causal_density_counts_markers_per_thousand(self):
        scorer = PMQualityScorerV2()
        content = '于是他很生气。因此他走了。所以结束了。'  # 3 个因果连词
        assert scorer._compute_causal_density(content) == pytest.approx(3 / len(content) * 1000, abs=0.01)

    def test_causal_density_empty(self):
        scorer = PMQualityScorerV2()
        assert scorer._compute_causal_density('') == 0.0

    def test_conflict_intensity_increases_with_conflicts(self):
        scorer = PMQualityScorerV2()
        calm = scorer._compute_conflict_intensity('他们平静地吃饭。')
        tense = scorer._compute_conflict_intensity('他们争吵并打斗，互相威胁。')
        assert tense > calm
        assert 0.0 <= tense <= 1.0

    def test_conflict_intensity_empty(self):
        scorer = PMQualityScorerV2()
        assert scorer._compute_conflict_intensity('') == 0.0

    def test_foreshadow_density(self):
        scorer = PMQualityScorerV2()
        content = '他似乎察觉到了什么，隐约觉得不安。'
        assert scorer._compute_foreshadow_density(content) > 0.0
        assert scorer._compute_foreshadow_density('') == 0.0


class TestRuleBasedFallback:
    """ai_service=None 时走规则评分，无 AI/DB 依赖"""

    def test_fallback_scores_all_dimensions(self):
        scorer = PMQualityScorerV2(ai_service=None)
        result = asyncio.run(scorer.score('第一章内容。他走进房间。', {}))
        assert set(result.scores.keys()) == set(DEFAULT_DIMENSIONS.keys())
        for v in result.scores.values():
            assert 0 <= v <= 100

    def test_fallback_pacing_high_when_single_paragraph(self):
        scorer = PMQualityScorerV2(ai_service=None)
        result = asyncio.run(scorer.score('长' * 100, {}))
        assert result.scores['pacing'] == 100  # 100/1段*2 → min(100, 200)

    def test_fallback_hook_depends_on_question_mark(self):
        scorer = PMQualityScorerV2(ai_service=None)
        with_hook = asyncio.run(scorer.score('他是谁？' + '长' * 50, {}))
        without_hook = asyncio.run(scorer.score('他走进房间。' + '长' * 50, {}))
        assert with_hook.scores['hook'] > without_hook.scores['hook']

    def test_fallback_hook_recognizes_fullwidth_question_mark(self):
        """回归：中文全角「？」也应触发 hook 高分（修复 ASCII-only 漏判）"""
        scorer = PMQualityScorerV2(ai_service=None)
        result = asyncio.run(scorer.score('他是谁？' + '长' * 50, {}))
        assert result.scores['hook'] == 80

    def test_fallback_outline_adherence_depends_on_seq_table(self):
        scorer = PMQualityScorerV2(ai_service=None)
        with_outline = asyncio.run(scorer.score('长' * 50, {'seq_table': '1.第一章 目标'}))
        without_outline = asyncio.run(scorer.score('长' * 50, {}))
        assert with_outline.scores['outline_adherence'] > without_outline.scores['outline_adherence']

    def test_fallback_suggestions_only_for_low_scores(self):
        scorer = PMQualityScorerV2(ai_service=None)
        # 高分样本（pacing=100，hook 含?=80）：suggestions 不应出现"需改进"
        result = asyncio.run(scorer.score('他是谁？' + '长' * 100, {}))
        for s in result.suggestions:
            assert '需改进' not in s

    def test_empty_content_no_crash(self):
        scorer = PMQualityScorerV2(ai_service=None)
        result = asyncio.run(scorer.score('', {}))
        assert result.scores


class TestScoreResult:
    def test_failed_dimensions(self):
        result = ScoreResult({'a': 50, 'b': 80, 'c': 90}, [], False)
        assert result.failed_dimensions == ['a']

    def test_no_failed_dimensions_when_all_pass(self):
        result = ScoreResult({'a': 70, 'b': 100}, [], True)
        assert result.failed_dimensions == []

    def test_total_score_defaults_to_mean(self):
        result = ScoreResult({'a': 100, 'b': 0}, [], False)
        assert result.total_score == 50.0

    def test_total_score_respects_passed_value(self):
        result = ScoreResult({'a': 100}, [], True, total_score=88.5)
        assert result.total_score == 88.5

    def test_empty_scores_no_division_by_zero(self):
        result = ScoreResult({}, [], False)
        assert result.total_score == 0.0


class TestImprovementHints:
    def test_known_dimensions_produce_hints(self):
        scorer = PMQualityScorerV2()
        hints = scorer._build_improvement_hints(['pacing: 50分 — 需改进', 'dialogue: 55分 — 需改进', 'hook: 40分 — 需改进'])
        assert '节奏' in hints
        assert '对话' in hints
        assert '钩子' in hints

    def test_unknown_dimension_skipped(self):
        scorer = PMQualityScorerV2()
        hints = scorer._build_improvement_hints(['unknown_dim: 30分 — 需改进'])
        assert hints == ''

    def test_max_three_hints(self):
        scorer = PMQualityScorerV2()
        hints = scorer._build_improvement_hints(
            ['pacing: 10', 'dialogue: 10', 'hook: 10', 'plot_logic: 10', 'character_consistency: 10']
        )
        assert len(hints.split('\n')) <= 3


class TestQualityLoopRegression:
    def test_max_retries_exists(self):
        """回归 bug#1：MAX_RETRIES 此前缺失导致 AttributeError"""
        assert QualityLoop.MAX_RETRIES == 3

    def test_max_retries_aligned_with_scorer(self):
        assert QualityLoop.MAX_RETRIES == PMQualityScorerV2.MAX_RETRIES
