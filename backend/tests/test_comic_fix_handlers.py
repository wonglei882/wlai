"""漫剧 fix handler 测试 — 3 个新增建议型 handler + 视觉 handler 签名回归。

覆盖（P0-2 成功标准）：
- 注册后通过 _FIX_HANDLERS / _has_auto_fix 命中
- _execute_fix 执行返回描述字符串
- 缺失字段 → 跳过描述（不抛错）
- db 异常 → 降级返回（_mark_panel_fix 内部吞掉，handler 不抛）
- _fix_visual_inconsistency 旧签名回归（修复前签名错位命中必抛 TypeError）
"""
from unittest.mock import AsyncMock, patch

from app.services.pm.pm_fix_executors import (
    _fix_dialogue_inconsistency,
    _fix_panel_transition,
    _fix_scene_discontinuity,
)
from app.services.pm.pm_fix_handlers import (
    _FIX_HANDLERS,
    _execute_fix,
    _fix_visual_inconsistency,
    _has_auto_fix,
    register_pm_handlers,
)


class FakePanel:
    """最小 ComicPanel 替身 — 仅暴露 scene_metadata。"""

    def __init__(self, scene_metadata=None):
        self.scene_metadata = scene_metadata if scene_metadata is not None else {}


class FakeResult:
    def __init__(self, panel=None):
        self._panel = panel

    def scalar_one_or_none(self):
        return self._panel


class FakeDB:
    """最小 AsyncSession 替身 — execute/flush/rollback，可配置异常。"""

    def __init__(self, panel=None, raise_on_execute=False):
        self._panel = panel
        self._raise = raise_on_execute

    async def execute(self, *args, **kwargs):
        if self._raise:
            raise RuntimeError('db boom')
        return FakeResult(self._panel)

    async def flush(self):
        pass

    async def rollback(self):
        pass


def _scene_issue(**overrides):
    issue = {
        'type': 'ca_scene_discontinuity',
        'severity': 'critical',
        'entities': ['panel:5', 'panel:6'],
        'conflict_type': 'time',
        'scene_from': '白天，村口集市',
        'scene_to': '深夜，村口集市',
        'page': 3,
    }
    issue.update(overrides)
    return issue


def _panel_issue(**overrides):
    issue = {
        'type': 'ca_panel_transition',
        'severity': 'info',
        'entities': ['panel:2', 'panel:2', 'panel:3', 'panel:4'],
        'issue': 'same_angle_streak',
        'angle': 'wide',
        'count': 4,
    }
    issue.update(overrides)
    return issue


def _dialogue_issue(**overrides):
    issue = {
        'type': 'ca_dialogue_inconsistency',
        'severity': 'warning',
        'entities': ['character:主角', 'panel:5', 'panel:6'],
        'character': '主角',
        'style_from': 'formal',
        'style_to': 'informal',
    }
    issue.update(overrides)
    return issue


class TestRegistration:
    def test_comic_handlers_registered_and_hittable(self):
        register_pm_handlers()
        for t in ('ca_scene_discontinuity', 'ca_panel_transition', 'ca_dialogue_inconsistency'):
            assert t in _FIX_HANDLERS, f'{t} 未注册'
            assert _has_auto_fix(t), f'{t} 无法命中'

    def test_visual_handler_still_registered(self):
        register_pm_handlers()
        assert 'ca_visual_inconsistency' in _FIX_HANDLERS
        assert _has_auto_fix('ca_visual_inconsistency')


class TestSceneFix:
    async def test_execute_fix_returns_desc(self):
        db = FakeDB(panel=FakePanel())
        with patch(
            'app.services.pm.self_tuning.choose_fix_strategy',
            new=AsyncMock(return_value=('aggressive', 0.9, 'test')),
        ):
            result = await _execute_fix(_scene_issue(), 'pid', 'uid', db)
        assert isinstance(result, str)
        assert '场景连续性修复建议' in result

    async def test_handler_returns_suggestion(self):
        db = FakeDB(panel=FakePanel())
        result = await _fix_scene_discontinuity(_scene_issue(), 'pid', 'uid', db)
        assert '场景连续性修复建议已生成' in result
        assert '统一为前镜' in result

    async def test_handler_writes_pm_fix_marker(self):
        panel = FakePanel()
        db = FakeDB(panel=panel)
        await _fix_scene_discontinuity(_scene_issue(), 'pid', 'uid', db)
        fixes = (panel.scene_metadata or {}).get('pm_fix', {})
        assert 'scene_discontinuity' in fixes
        assert 'suggestion' in fixes['scene_discontinuity']

    async def test_missing_fields_skips(self):
        db = FakeDB(panel=FakePanel())
        result = await _fix_scene_discontinuity(
            _scene_issue(entities=[], scene_from='', scene_to=''), 'pid', 'uid', db
        )
        assert '跳过' in result

    async def test_db_error_degrades_without_raise(self):
        db = FakeDB(panel=FakePanel(), raise_on_execute=True)
        result = await _fix_scene_discontinuity(_scene_issue(), 'pid', 'uid', db)
        assert isinstance(result, str)
        # 标记写入失败 → 不带"已写入"后缀，但仍返回建议描述（不抛错）
        assert '已写入分镜修复标记' not in result


class TestPanelFix:
    async def test_handler_returns_suggestion(self):
        db = FakeDB(panel=FakePanel())
        result = await _fix_panel_transition(_panel_issue(), 'pid', 'uid', db)
        assert '分镜衔接修复建议已生成' in result
        assert 'camera_angle' in result

    async def test_missing_entities_skips(self):
        db = FakeDB(panel=FakePanel())
        result = await _fix_panel_transition(_panel_issue(entities=[]), 'pid', 'uid', db)
        assert '跳过' in result

    async def test_db_error_degrades_without_raise(self):
        db = FakeDB(panel=FakePanel(), raise_on_execute=True)
        result = await _fix_panel_transition(_panel_issue(), 'pid', 'uid', db)
        assert isinstance(result, str)


class TestDialogueFix:
    async def test_handler_returns_suggestion(self):
        db = FakeDB(panel=FakePanel())
        result = await _fix_dialogue_inconsistency(_dialogue_issue(), 'pid', 'uid', db)
        assert '对话语气统一建议已生成' in result
        assert '主角' in result

    async def test_missing_character_skips(self):
        db = FakeDB(panel=FakePanel())
        result = await _fix_dialogue_inconsistency(
            _dialogue_issue(character='', entities=['panel:5']), 'pid', 'uid', db
        )
        assert '跳过' in result

    async def test_db_error_degrades_without_raise(self):
        db = FakeDB(panel=FakePanel(), raise_on_execute=True)
        result = await _fix_dialogue_inconsistency(_dialogue_issue(), 'pid', 'uid', db)
        assert isinstance(result, str)


class TestVisualFixRegression:
    """修复前 _fix_visual_inconsistency 签名错位（scan_round 无默认值）命中必抛 TypeError。

    回归：旧签名 (issue, project_id, user_id, db) -> str 可正常调用并返回描述字符串。
    """

    async def test_retry_action_returns_str(self):
        with patch('app.services.comic.visual_retry.VisualRetryService') as mock_cls:
            instance = mock_cls.return_value
            instance.handle_visual_issue = AsyncMock(
                return_value={'action': 'retry', 'attempt': 2, 'shot_id': 'shot12345678'}
            )
            result = await _fix_visual_inconsistency(
                {'type': 'ca_visual_inconsistency'}, 'pid', 'uid', FakeDB()
            )
        assert result == '视觉重试第2次 (shot=shot1234)'

    async def test_escalate_action_returns_str(self):
        with patch('app.services.comic.visual_retry.VisualRetryService') as mock_cls:
            instance = mock_cls.return_value
            instance.handle_visual_issue = AsyncMock(
                return_value={'action': 'escalate', 'shot_id': 'shot12345678'}
            )
            result = await _fix_visual_inconsistency(
                {'type': 'ca_visual_inconsistency'}, 'pid', 'uid', FakeDB()
            )
        assert '转人工审核' in result
        assert isinstance(result, str)

    async def test_skip_action_returns_str(self):
        with patch('app.services.comic.visual_retry.VisualRetryService') as mock_cls:
            instance = mock_cls.return_value
            instance.handle_visual_issue = AsyncMock(
                return_value={'action': 'skip', 'reason': '无目标镜头信息'}
            )
            result = await _fix_visual_inconsistency(
                {'type': 'ca_visual_inconsistency'}, 'pid', 'uid', FakeDB()
            )
        assert result == '跳过: 无目标镜头信息'

    async def test_exception_degrades_to_str(self):
        with patch('app.services.comic.visual_retry.VisualRetryService') as mock_cls:
            instance = mock_cls.return_value
            instance.handle_visual_issue = AsyncMock(side_effect=RuntimeError('boom'))
            result = await _fix_visual_inconsistency(
                {'type': 'ca_visual_inconsistency'}, 'pid', 'uid', FakeDB()
            )
        assert isinstance(result, str)
        assert '视觉重试异常' in result