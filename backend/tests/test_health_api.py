"""测试健康检查端点。"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestLiveness:
    """存活探针测试。"""

    @pytest.mark.asyncio
    async def test_liveness_returns_ok(self):
        from app.api.health import liveness
        result = await liveness()
        assert result['status'] == 'ok'
        assert result['service'] == 'wlai-pm-backend'
        assert 'version' in result
        assert 'timestamp' in result


class TestReadiness:
    """就绪探针测试。"""

    @pytest.mark.asyncio
    async def test_readiness_all_down(self):
        """DB 和 Redis 都不可达时应返回 degraded。"""
        with patch('app.api.health._check_database', new_callable=lambda: AsyncMock(return_value={'status': 'error'})), \
             patch('app.api.health._check_redis', return_value={'status': 'error'}):
            from app.api.health import readiness
            result = await readiness()
            assert result['status'] == 'degraded'
            assert result['components']['database']['status'] == 'error'
            assert result['components']['redis']['status'] == 'error'

    @pytest.mark.asyncio
    async def test_readiness_all_ok(self):
        """DB 和 Redis 都正常时应返回 ok。"""
        with patch('app.api.health._check_database', new_callable=lambda: AsyncMock(return_value={'status': 'ok'})), \
             patch('app.api.health._check_redis', return_value={'status': 'ok'}):
            from app.api.health import readiness
            result = await readiness()
            assert result['status'] == 'ok'
            assert result['components']['database']['status'] == 'ok'

    @pytest.mark.asyncio
    async def test_readiness_partial_degradation(self):
        """DB 正常但 Redis 异常时应返回 degraded。"""
        with patch('app.api.health._check_database', new_callable=lambda: AsyncMock(return_value={'status': 'ok'})), \
             patch('app.api.health._check_redis', return_value={'status': 'error'}):
            from app.api.health import readiness
            result = await readiness()
            assert result['status'] == 'degraded'


class TestMetrics:
    """指标端点测试。"""

    @pytest.mark.asyncio
    async def test_metrics_returns_process_info(self):
        with patch('app.database._session_stats', {'created': 10, 'closed': 8, 'active': 2, 'errors': 0, 'generator_exits': 0}), \
             patch('app.database._engine_cache', {}):
            from app.api.health import metrics
            result = await metrics()
            assert 'process' in result
            assert 'memory_mb' in result['process']
            assert 'cpu_percent' in result['process']
            assert 'database' in result
            assert 'timestamp' in result
