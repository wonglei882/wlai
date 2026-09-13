"""测试 PM 控制 API（Kill Switch / Pause / Resume）。"""

import pytest
from unittest.mock import patch, MagicMock
import json


class TestPMControlState:
    """PM 控制状态管理测试。"""

    def test_default_state(self):
        from app.api.pm_control import _default_state
        state = _default_state()
        assert state['kill_switch'] is False
        assert state['pause_switch'] is False
        assert state['killed_at'] is None
        assert state['paused_at'] is None

    def test_load_state_from_file_missing(self):
        """状态文件不存在时应返回默认状态。"""
        from app.api.pm_control import _load_state_from_file
        with patch('app.api.pm_control._STATE_FILE') as mock_path:
            mock_path.exists.return_value = False
            state = _load_state_from_file()
            assert state['kill_switch'] is False

    def test_load_state_from_file_corrupted(self):
        """状态文件损坏时应返回默认状态。"""
        from app.api.pm_control import _load_state_from_file
        with patch('app.api.pm_control._STATE_FILE') as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = 'not valid json{{{'
            state = _load_state_from_file()
            assert state['kill_switch'] is False

    def test_load_state_from_redis_corrupted(self):
        """Redis 数据损坏时应返回默认状态。"""
        from app.api.pm_control import _load_state_from_redis
        mock_redis = MagicMock()
        mock_redis.get.return_value = 'corrupted json{{'
        with patch('app.api.pm_control._get_redis', return_value=mock_redis):
            state = _load_state_from_redis()
            assert state['kill_switch'] is False

    def test_load_state_from_redis_none(self):
        """Redis 不可用时应返回默认状态。"""
        from app.api.pm_control import _load_state_from_redis
        with patch('app.api.pm_control._get_redis', return_value=None):
            state = _load_state_from_redis()
            assert state['kill_switch'] is False

    def test_save_state_to_file(self, tmp_path):
        """保存状态到文件应可回读。"""
        from app.api.pm_control import _save_state_to_file
        state_file = tmp_path / 'state.json'
        with patch('app.api.pm_control._STATE_FILE', state_file), \
             patch('app.api.pm_control._ensure_data_dir'):
            _save_state_to_file({'kill_switch': True, 'pause_switch': False, 'killed_at': '2026-01-01', 'paused_at': None})
            data = json.loads(state_file.read_text())
            assert data['kill_switch'] is True

    def test_save_state_to_redis(self):
        """保存状态到 Redis 应调用 set。"""
        from app.api.pm_control import _save_state_to_redis
        mock_redis = MagicMock()
        with patch('app.api.pm_control._get_redis', return_value=mock_redis):
            _save_state_to_redis({'kill_switch': True, 'pause_switch': False})
            mock_redis.set.assert_called_once()


class TestPMControlAPI:
    """PM 控制 API 端点测试。"""

    @pytest.mark.asyncio
    async def test_get_pm_status(self):
        """获取 PM 状态应返回完整结构。"""
        from app.api.pm_control import get_pm_status
        with patch('app.api.pm_control.PMControlState') as mock_state:
            mock_state.get_status.return_value = {
                'kill_switch': False,
                'pause_switch': False,
                'killed_at': None,
                'paused_at': None,
            }
            with patch('app.api.pm_control.get_pm_health', return_value={'status': 'ok'}, create=True):
                result = await get_pm_status()
                assert 'kill_switch' in result
                assert 'health' in result

    @pytest.mark.asyncio
    async def test_get_pm_status_health_error(self):
        """健康检查获取失败不应阻断状态返回。"""
        from app.api.pm_control import get_pm_status
        with patch('app.api.pm_control.PMControlState') as mock_state:
            mock_state.get_status.return_value = {
                'kill_switch': False, 'pause_switch': False,
                'killed_at': None, 'paused_at': None,
            }
            with patch('app.services.pm.pm_api.get_pm_health', side_effect=Exception('boom')):
                result = await get_pm_status()
                assert result['health']['error'] == '健康检查不可用'
