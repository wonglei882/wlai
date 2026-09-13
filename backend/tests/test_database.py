"""测试数据库会话管理。"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestSessionStats:
    """会话统计测试。"""

    @pytest.mark.asyncio
    async def test_reset_session_stats(self):
        """重置后统计应归零。"""
        from app.database import reset_session_stats
        result = await reset_session_stats()
        assert result['created'] == 0
        assert result['closed'] == 0
        assert result['active'] == 0
        assert result['errors'] == 0

    def test_session_stats_initial_state(self):
        """初始统计应有基本字段。"""
        from app.database import _session_stats
        assert 'created' in _session_stats
        assert 'closed' in _session_stats
        assert 'active' in _session_stats
        assert 'errors' in _session_stats


class TestEngineCache:
    """引擎缓存测试。"""

    def test_engine_cache_is_dict(self):
        from app.database import _engine_cache
        assert isinstance(_engine_cache, dict)

    def test_engine_cache_initially_empty_or_populated(self):
        """引擎缓存可以是空或已填充（取决于之前的使用）。"""
        from app.database import _engine_cache
        assert isinstance(_engine_cache, dict)


class TestDatabaseHealth:
    """数据库健康检查测试。"""

    @pytest.mark.asyncio
    async def test_get_db_session_for_health_yields_session(self):
        """健康检查会话生成器应 yield 一个 AsyncSession。"""
        with patch('app.database.settings') as mock_settings:
            mock_settings.database_url = 'sqlite+aiosqlite:///test_health.db'
            from app.database import get_db_session_for_health
            async for session in get_db_session_for_health():
                assert session is not None
                break  # 只需要验证能 yield


class TestDatabaseConfig:
    """数据库配置测试。"""

    def test_session_maker_cache_is_dict(self):
        from app.database import _session_maker_cache
        assert isinstance(_session_maker_cache, dict)

    def test_slow_query_threshold_positive(self):
        from app.config import settings
        assert settings.database_slow_query_threshold > 0

    def test_database_metrics_enabled(self):
        from app.config import settings
        assert settings.database_enable_metrics is True
