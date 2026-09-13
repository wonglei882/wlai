"""测试 API v1 公共依赖（deps.py）。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.api.v1.deps import get_current_user_id


class TestGetCurrentUserId:
    """get_current_user_id 依赖测试。"""

    @pytest.mark.asyncio
    async def test_missing_user_id_raises_401(self):
        """无 user_id 时应返回 401。"""
        from fastapi import HTTPException

        request = MagicMock()
        request.state = MagicMock()
        # 模拟没有 user_id
        type(request.state).user_id = property(lambda self: None)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(request)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_user_id(self):
        """有 user_id 时应正常返回。"""
        request = MagicMock()
        request.state = MagicMock()
        request.state.user_id = 'test_user_123'

        result = await get_current_user_id(request)
        assert result == 'test_user_123'

    @pytest.mark.asyncio
    async def test_empty_user_id_raises_401(self):
        """空字符串 user_id 应返回 401。"""
        from fastapi import HTTPException

        request = MagicMock()
        request.state = MagicMock()
        request.state.user_id = ''

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(request)
        assert exc_info.value.status_code == 401
