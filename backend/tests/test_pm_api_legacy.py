"""测试 PM 旧 API 异常改造后不再泄露内部异常。"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.core.exceptions import SystemException


class TestPMExceptionSafety:
    """验证 pm.py 端点不再用 HTTPException(500) 泄露 str(e)。"""

    @pytest.mark.asyncio
    async def test_trigger_inspection_raises_system_exception(self):
        """巡检触发失败时应抛 SystemException 而非 HTTPException。"""
        with patch('app.services.pm.pm_api.scan_all_projects', new_callable=lambda: AsyncMock(side_effect=Exception('DB timeout'))):
            from app.api.pm import trigger_rerun
            with pytest.raises(SystemException, match='巡检触发失败'):
                await trigger_rerun()

    @pytest.mark.asyncio
    async def test_proactive_inspect_raises_system_exception(self):
        """巡检失败时应抛 SystemException。"""
        mock_db = MagicMock()
        with patch('app.api.pm._validate_project_ownership', new_callable=lambda: AsyncMock()), \
             patch('app.services.pm.pm_proactive_inspector.run_proactive_inspection',
                   new_callable=lambda: AsyncMock(side_effect=Exception('scan error'))):
            from app.api.pm import proactive_inspect
            with pytest.raises(SystemException, match='巡检失败'):
                await proactive_inspect('proj_123', 'user_456', mock_db)

    @pytest.mark.asyncio
    async def test_get_proactive_report_raises_system_exception(self):
        """主动汇报器失败时应抛 SystemException。"""
        mock_db = MagicMock()
        with patch('app.api.pm._validate_project_ownership', new_callable=lambda: AsyncMock()), \
             patch('app.services.proactive_reporter.reporter') as mock_reporter:
            mock_reporter.check = AsyncMock(side_effect=Exception('reporter error'))
            from app.api.pm import get_proactive_report
            with pytest.raises(SystemException, match='主动汇报器调用失败'):
                await get_proactive_report('proj_123', 'user_456', mock_db)

    @pytest.mark.asyncio
    async def test_get_suggestions_raises_system_exception(self):
        """主动建议失败时应抛 SystemException。"""
        mock_db = MagicMock()
        with patch('app.api.pm._validate_project_ownership', new_callable=lambda: AsyncMock()), \
             patch('app.services.proactive_suggestions.generate_proactive_suggestions',
                   new_callable=lambda: AsyncMock(side_effect=Exception('suggestion error'))):
            from app.api.pm import get_proactive_suggestions
            with pytest.raises(SystemException, match='主动建议调用失败'):
                await get_proactive_suggestions('proj_123', 'user_456', mock_db)

    def test_system_exception_not_http_exception(self):
        """SystemException 不应是 HTTPException 的子类。"""
        from fastapi import HTTPException
        assert not issubclass(SystemException, HTTPException)

    def test_system_exception_caught_by_global_handler(self):
        """SystemException 应是 Exception 的子类（被全局处理器捕获）。"""
        assert issubclass(SystemException, Exception)
