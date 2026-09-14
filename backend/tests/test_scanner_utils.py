"""pm_scanners 纯函数测试（不依赖测试库）。

覆盖：
- _safe_json_loads：dict 直通 / 合法 JSON / 脏数据回退
- _extract_chapter_from_range：章节区间解析 + 非法输入回退
- SCAN_REGISTRY：注册表完整性（新增维度后此处会失败，提醒补测试）
"""
import json

from app.services.pm.pm_scanners import (
    SCAN_REGISTRY,
    _extract_chapter_from_range,
    _safe_json_loads,
)


class TestSafeJsonLoads:
    def test_dict_passthrough(self):
        raw = {'foreshadow': 'x'}
        assert _safe_json_loads(raw) is raw

    def test_valid_json_str(self):
        raw = json.dumps({'foreshadow': 'x'})
        assert _safe_json_loads(raw) == {'foreshadow': 'x'}

    def test_dirty_str_falls_back_empty(self):
        assert _safe_json_loads('{not json') == {}

    def test_empty_str_falls_back_empty(self):
        assert _safe_json_loads('') == {}

    def test_none_falls_back_empty(self):
        assert _safe_json_loads(None) == {}


class TestExtractChapterFromRange:
    def test_standard_range(self):
        assert _extract_chapter_from_range('第12章→第15章') == 12

    def test_whitespace_tolerance(self):
        assert _extract_chapter_from_range(' 第3章 → 第5章 ') == 3

    def test_non_digit_start_falls_back_zero(self):
        assert _extract_chapter_from_range('序章→第5章') == 0

    def test_missing_arrow_falls_back_zero(self):
        assert _extract_chapter_from_range('第12章') == 0

    def test_empty_falls_back_zero(self):
        assert _extract_chapter_from_range('') == 0


class TestScanRegistry:
    """注册表完整性守卫：新增诊断维度后必须补充测试。"""

    EXPECTED = {
        'character_consistency',
        'foreshadow_age',
        'world_rule_drift',
        'outline_drift',
        'quality_score',
        'paragraph_format',
        # 红线检测（Phase 2：命中红线强制转人工）
        'red_line_check',
        # 漫剧维度（事后巡检适配）
        'visual_consistency',
        'scene_continuity',
        'panel_transition',
        'dialogue_bubble',
        'comic_quality_score',
    }

    def test_registry_contains_expected_dimensions(self):
        assert set(SCAN_REGISTRY.keys()) == self.EXPECTED

    def test_each_dimension_has_required_fields(self):
        for name, entry in SCAN_REGISTRY.items():
            assert entry.get('issue_type'), f'{name} 缺 issue_type'
            assert callable(entry.get('fn')), f'{name} 缺可调用 handler'
            assert callable(entry.get('diag_msg_fn')), f'{name} 缺 diag_msg_fn'
