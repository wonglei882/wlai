"""独立部署补齐模块的测试。

覆盖：
1. 12 个此前 MISSING 的懒加载模块可导入
2. detect_progress_trend 趋势判断逻辑
3. CommandExecutor 命令解析与执行（含异常路径）
4. 降级桩行为（mcp / quality_forecast / causal_graph / proactive_session）
"""
import pytest


class TestMissingModulesImportable:
    """此前 check_deps 报 MISSING 的模块，补齐后应全部可导入。"""

    MISSING_MODULES = [
        'app.agent.core.command_executor',
        'app.agent.domain.commands',
        'app.agent.domain.register',
        'app.agent.infrastructure.progress_analyzer',
        'app.api.chapters.generate_analysis',
        'app.api.settings',
        'app.mcp',
        'app.models.analysis_task',
        'app.services.inspiration_sub.proactive_session',
        'app.services.project_manager_service',
        'app.services.quality_forecast',
        'app.utils.redis_client',
        'app.services.guardian.causal_graph',
    ]

    @pytest.mark.parametrize('module', MISSING_MODULES)
    def test_importable(self, module):
        import importlib

        importlib.import_module(module)


class TestProgressTrend:
    """detect_progress_trend 的趋势判断。"""

    def test_upward_trend(self):
        from app.agent.infrastructure.progress_analyzer import detect_progress_trend

        result = detect_progress_trend([50, 55, 60, 68, 72, 78])
        assert result['trend'] == '上升'
        assert result['confidence'] > 0

    def test_downward_trend(self):
        from app.agent.infrastructure.progress_analyzer import detect_progress_trend

        result = detect_progress_trend([80, 75, 70, 62, 55, 50])
        assert result['trend'] == '下降'

    def test_flat_trend(self):
        from app.agent.infrastructure.progress_analyzer import detect_progress_trend

        result = detect_progress_trend([60, 61, 59, 60, 62, 60])
        assert result['trend'] == '平稳'

    def test_insufficient_samples(self):
        from app.agent.infrastructure.progress_analyzer import detect_progress_trend

        result = detect_progress_trend([60, 70])
        assert result['trend'] == '平稳'
        assert result['confidence'] == 0.0

    def test_empty_input(self):
        from app.agent.infrastructure.progress_analyzer import detect_progress_trend

        result = detect_progress_trend([])
        assert result['trend'] == '平稳'


class TestCommandExecutor:
    """CommandExecutor 的命令解析与执行。"""

    async def test_execute_registered_tool(self):
        from app.agent.core.command_executor import CommandExecutor
        from app.agent.core.command_registry import RiskLevel, ToolDefinition, ToolRegistry

        async def handler(params, db):
            return [f"got={params['x']}"]

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name='echo',
                description='echo x',
                params_schema={'x': 'str'},
                required_params=['x'],
                handler=handler,
                param_types={'x': 'int'},
                risk_level=RiskLevel.LOW,
            )
        )
        executor = CommandExecutor(registry=registry, db=None)
        results = await executor.execute_text('[TOOL:echo|x=42]')
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].logs == ['got=42']

    async def test_execute_unknown_tool(self):
        from app.agent.core.command_executor import CommandExecutor
        from app.agent.core.command_registry import ToolRegistry

        executor = CommandExecutor(registry=ToolRegistry(), db=None)
        results = await executor.execute_text('[TOOL:nope|a=1]')
        assert results[0].success is False
        assert '未注册' in results[0].logs[0]

    async def test_execute_malformed_text(self):
        from app.agent.core.command_executor import CommandExecutor
        from app.agent.core.command_registry import ToolRegistry

        executor = CommandExecutor(registry=ToolRegistry(), db=None)
        results = await executor.execute_text('没有工具命令')
        assert results[0].success is False

    async def test_handler_exception_is_captured(self):
        from app.agent.core.command_executor import CommandExecutor
        from app.agent.core.command_registry import RiskLevel, ToolDefinition, ToolRegistry

        async def handler(params, db):
            raise ValueError('boom')

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name='fail_tool',
                description='always fails',
                params_schema={},
                required_params=[],
                handler=handler,
                param_types={},
                risk_level=RiskLevel.LOW,
            )
        )
        executor = CommandExecutor(registry=registry, db=None)
        results = await executor.execute_text('[TOOL:fail_tool]')
        assert results[0].success is False
        assert 'boom' in results[0].logs[0]


class TestDegradedStubs:
    """独立部署降级桩的行为。"""

    async def test_mcp_client_noop(self):
        from app.mcp import mcp_client

        results = await mcp_client.batch_call_tools(user_id='u1', tool_calls=[{'name': 'x'}])
        assert results == []
        assert mcp_client.build_tool_context(results) == ''

    async def test_quality_forecast_empty(self):
        from app.services.quality_forecast import generate_forecast, get_risk_summary

        risks = await generate_forecast(db=None, project_id='p1', chapter_id='c1')
        assert risks == []
        assert get_risk_summary(risks) == ''

    async def test_causal_graph_noop(self):
        from app.services.guardian import causal_graph

        assert await causal_graph.infer_from_content(None, 'c1', 'p1', '内容') == 0
        assert await causal_graph.get_impact_warning(None, 'c1', 'p1') == ''
        assert await causal_graph.delete_for_chapter(None, 'c1', 'p1') == 0

    def test_proactive_session_noop(self):
        from app.services.inspiration_sub.proactive_session import _ensure_global_skills

        # 空实现不应抛异常
        _ensure_global_skills()
