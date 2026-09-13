"""测试 Companion 陪伴 API。"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestCompanionHelpers:
    """Companion 辅助函数测试。"""

    @pytest.mark.asyncio
    async def test_companion_enabled_returns_bool(self):
        """功能开关应返回布尔值。"""
        with patch('app.services.pm.feature_config.is_pm_feature_enabled', return_value=True):
            from app.api.companion import _companion_enabled
            result = await _companion_enabled()
            assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_companion_disabled(self):
        """功能关闭时应返回 False。"""
        with patch('app.services.pm.feature_config.is_pm_feature_enabled', return_value=False):
            from app.api.companion import _companion_enabled
            result = await _companion_enabled()
            assert result is False

    @pytest.mark.asyncio
    async def test_companion_enabled_feature_read_error(self):
        """功能开关读取失败时应降级返回 False。"""
        with patch('app.services.pm.feature_config.is_pm_feature_enabled', side_effect=Exception('config error')):
            from app.api.companion import _companion_enabled
            result = await _companion_enabled()
            assert result is False

    @pytest.mark.asyncio
    async def test_get_profile_returns_none_for_missing_user(self):
        """不存在的用户应返回 None。"""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.api.companion import _get_profile
        profile = await _get_profile(mock_db, 'nonexistent_user')
        assert profile is None

    @pytest.mark.asyncio
    async def test_validate_project_ownership_raises_for_wrong_owner(self):
        """非项目所有者应抛 403。"""
        from fastapi import HTTPException

        mock_db = MagicMock()
        mock_project = MagicMock()
        mock_project.user_id = 'other_user'
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.api.companion import _validate_project_ownership
        with pytest.raises(HTTPException) as exc_info:
            await _validate_project_ownership(mock_db, 'proj_1', 'wrong_user')
        assert exc_info.value.status_code == 403


class TestCompanionRouter:
    """Companion 路由注册测试。"""

    def test_router_prefix(self):
        from app.api.companion import router
        assert router.prefix == '/companion'

    def test_router_has_routes(self):
        from app.api.companion import router
        assert len(router.routes) > 0
