"""AI服务封装 - 统一的AI接口

重构后支持自动MCP工具加载：
- 所有AI方法在请求前自动检查用户MCP配置
- 如果有启用的MCP插件且有可用工具，自动发送tools
- 通过 auto_mcp 参数控制是否启用自动工具加载
"""

from typing import Any
from collections.abc import AsyncGenerator, Callable

from app.config import settings as app_settings
import logging
from app.services.ai.ai_config import AIClientConfig, default_config
from app.services.ai.ai_metrics import AICallMetrics, TokenUsage, ToolCallMetrics
from app.services.ai_clients.openai_client import OpenAIClient
from app.services.ai_clients.anthropic_client import AnthropicClient
from app.services.ai_clients.gemini_client import GeminiClient
from app.services.ai_clients.base_client import cleanup_all_clients
from app.services.ai_providers.openai_provider import OpenAIProvider
from app.services.ai_providers.anthropic_provider import AnthropicProvider
from app.services.ai_providers.gemini_provider import GeminiProvider
from app.services.ai_providers.base_provider import BaseAIProvider
from app.services.json_helper import clean_json_response, parse_json

# 导出清理函数
cleanup_http_clients = cleanup_all_clients

logger = logging.getLogger(__name__)


def normalize_provider(provider: str | None) -> str | None:
    """标准化 provider 名称，兼容渠道别名。"""
    if provider == 'mumu':
        return 'openai'
    return provider


async def _execute_pm_tools(
    service: 'AIService',
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """执行 PM 工具调用（通过 CommandExecutor）"""
    import json as _json
    from app.agent.core.command_registry import ToolRegistry
    from app.agent.core.command_executor import CommandExecutor
    from app.agent.domain.commands import register_all_tools as register_base_tools
    from app.agent.domain.register import register_all_tools as register_ext_tools

    registry = ToolRegistry()
    register_base_tools(registry)  # base: read_project, read_chapter, list_chapters 等
    register_ext_tools(registry)  # ext: analyze, foreshadow, brainstorm 等

    # 获取 db
    db = getattr(service, 'db_session', None)
    project_id = getattr(service, '_last_project_id', None)
    logger.warning(f'⚠️ PM工具执行: project_id={project_id}, db={"有" if db else "无"}')

    user_id = service.user_id

    results = []
    for tc in tool_calls:
        tool_call_id = tc.get('id', 'unknown')
        func = tc.get('function', {})
        func_name = func.get('name', '')
        tool_name = func_name[3:] if func_name.startswith('pm_') else func_name

        try:
            arguments = func.get('arguments', '{}')
            if isinstance(arguments, str):
                arguments = _json.loads(arguments)
        except Exception:
            arguments = {}

        # 🔍 诊断日志：记录工具调用的原始参数
        logger.warning(f'🔍 PM工具调用: tool={tool_name}, args={arguments}, project_id={project_id}')

        try:
            executor = CommandExecutor(
                registry=registry,
                db=db,
                user_id=user_id,
                project_id=project_id,
            )
            cmd_text = f'[TOOL:{tool_name}]'
            if arguments:
                param_str = '&'.join(f'{k}={v}' for k, v in arguments.items())
                if param_str:
                    cmd_text = f'[TOOL:{tool_name}|{param_str}]'

            raw_results = await executor.execute_text(cmd_text)
            logs = []
            for r in raw_results:
                logs.extend(r.logs)

            # 🔍 诊断日志：记录工具返回的内容（前300字）
            result_preview = '\n'.join(logs)[:300]
            logger.warning(f'✅ PM工具返回 [{tool_name}]: {result_preview}')

            results.append(
                {
                    'tool_call_id': tool_call_id,
                    'role': 'tool',
                    'name': func_name,
                    'content': '\n'.join(logs),
                    'success': True,
                }
            )
        except Exception as e:
            results.append(
                {
                    'tool_call_id': tool_call_id,
                    'role': 'tool',
                    'name': func_name,
                    'content': f'PM工具调用失败: {str(e)}',
                    'success': False,
                    'error': str(e),
                }
            )

    return results


class AIService:
    """
    AI服务统一接口

    MCP工具支持：
    - 在创建服务时传入 user_id 和 db_session
    - 根据用户MCP插件的enabled状态自动决定是否启用MCP
    - 如果有任意一个MCP插件启用，则加载并使用工具
    - 如果所有插件都关闭，则不使用任何MCP工具
    - 通过 auto_mcp=False 可临时禁用自动工具加载
    - 通过 mcp_max_rounds 控制工具调用轮数
    - 通过 clear_mcp_cache() 可清理MCP工具缓存

    MCP启用逻辑（backend/app/api/settings.py 中的 get_user_ai_service）：
    - 查询用户的所有MCP插件
    - 如果有启用的插件 (enabled=True)，则 enable_mcp=True
    - 如果所有插件都关闭或没有插件，则 enable_mcp=False

    使用示例：
        # 创建支持MCP的AI服务（根据插件状态自动决定是否启用）
        ai_service = create_user_ai_service_with_mcp(
            api_provider="openai",
            api_key="...",
            user_id="user123",
            db_session=db
        )

        # 自动加载MCP工具（如果有启用的插件）
        result = await ai_service.generate_text(prompt="...")

        # 临时禁用MCP工具
        result = await ai_service.generate_text(prompt="...", auto_mcp=False)

        # 自定义轮数
        result = await ai_service.generate_text(prompt="...", mcp_max_rounds=3)
    """

    def __init__(
        self,
        api_provider: str | None = None,
        api_key: str | None = None,
        api_base_url: str | None = None,
        default_model: str | None = None,
        default_temperature: float | None = None,
        default_max_tokens: int | None = None,
        default_system_prompt: str | None = None,
        config: AIClientConfig | None = None,
        # MCP支持参数
        user_id: str | None = None,
        db_session: Any | None = None,
        enable_mcp: bool = True,
    ):
        """初始化

        Args:
            self:
            api_provider:
            api_key:
            api_base_url:
            default_model:
            default_temperature:
            default_max_tokens:
            default_system_prompt:
            config:
            user_id:
            db_session:
            enable_mcp:

        Returns:
            None
        """
        self.api_provider = normalize_provider(api_provider or app_settings.default_ai_provider)
        self.default_model = default_model or app_settings.default_model
        self.default_temperature = default_temperature or app_settings.default_temperature
        self.default_max_tokens = default_max_tokens or app_settings.default_max_tokens
        self.default_system_prompt = default_system_prompt
        self.config = config or default_config

        # MCP配置
        self.user_id = user_id
        self.db_session = db_session
        self._enable_mcp = enable_mcp
        self._cached_tools: list[dict] | None = None
        self._tools_loaded = False

        self._openai_provider: OpenAIProvider | None = None
        self._anthropic_provider: AnthropicProvider | None = None
        self._gemini_provider: GeminiProvider | None = None

        # 初始化 OpenAI
        openai_key = api_key or app_settings.openai_api_key
        if openai_key:
            base_url = api_base_url or app_settings.openai_base_url
            client = OpenAIClient(openai_key, base_url or 'https://api.openai.com/v1', self.config)
            self._openai_provider = OpenAIProvider(client)

        # 初始化 Anthropic
        anthropic_key = api_key or app_settings.anthropic_api_key
        if anthropic_key:
            base_url = api_base_url or app_settings.anthropic_base_url
            client = AnthropicClient(anthropic_key, base_url, self.config)
            self._anthropic_provider = AnthropicProvider(client)

        # 初始化 Gemini
        if self.api_provider == 'gemini':
            gemini_key = api_key or app_settings.gemini_api_key
            if gemini_key:
                base_url = api_base_url or app_settings.gemini_base_url
                client = GeminiClient(gemini_key, base_url, self.config)
                self._gemini_provider = GeminiProvider(client)

    @property
    def enable_mcp(self) -> bool:
        """是否启用MCP工具"""
        return self._enable_mcp

    def set_enable_mcp(self, value: bool):
        """设置MCP启用状态，如果禁用则清理缓存。

        注意：已移除 @enable_mcp.setter property setter（无调用方，纯误报）。
        """
        if value is False and self._enable_mcp is True:
            # 从启用变为禁用，清理缓存
            self.clear_mcp_cache()
        self._enable_mcp = value

    def clear_mcp_cache(self):
        """
        清理MCP工具缓存

        当禁用MCP时调用此方法，确保后续AI调用不会使用缓存的工具。
        同时更新 _tools_loaded 状态，使下次调用时重新检查。
        """
        if self._cached_tools is not None:
            logger.info(f'🔧 清理MCP工具缓存，移除 {len(self._cached_tools)} 个工具')
            self._cached_tools = None
        else:
            logger.debug('🔧 MCP工具缓存已经是空，无需清理')

        # 更新加载状态，确保下次调用会重新检查
        self._tools_loaded = False
        logger.debug(f'🔧 MCP工具状态已重置: enable_mcp={self._enable_mcp}, _tools_loaded=False')

    def _get_provider(self, provider: str | None = None) -> BaseAIProvider:
        """获取对应的 Provider"""
        p = normalize_provider(provider or self.api_provider)
        if p == 'openai' and self._openai_provider:
            return self._openai_provider
        if p == 'anthropic' and self._anthropic_provider:
            return self._anthropic_provider
        if p == 'gemini' and self._gemini_provider:
            return self._gemini_provider
        raise ValueError(f'Provider {p} 未初始化')

    def _build_call_metrics(
        self,
        *,
        request_mode: str,
        provider: str | None,
        model: str | None,
        prompt: str,
        auto_mcp: bool,
        tools_count: int,
        stream: bool,
    ) -> AICallMetrics:
        """构建CallMetrics

        Args:
            self:

        Returns:
            AICallMetrics
        """
        return AICallMetrics(
            request_mode=request_mode,
            provider=normalize_provider(provider or self.api_provider) or 'unknown',
            model=model or self.default_model,
            user_id=self.user_id,
            stream=stream,
            auto_mcp=auto_mcp,
            tools_count=tools_count,
            prompt_length=len(prompt or ''),
        )

    def _log_call_metrics(self, metrics: AICallMetrics, title: str | None = None):
        """LogCallMetrics

        Args:
            self:
            metrics:
            title:

        Returns:
            None
        """
        log_title = title or ('AI调用完成' if metrics.success else 'AI调用失败')
        message = metrics.to_log_message(log_title)
        if metrics.success:
            logger.info(message)
        else:
            logger.error(message)

    async def _prepare_mcp_tools(self, auto_mcp: bool = True, force_refresh: bool = False) -> list[dict] | None:
        """
        预处理MCP工具

        检查用户MCP配置并加载可用工具。
        结果会被缓存，避免重复加载。

        Args:
            auto_mcp: 是否自动加载MCP工具（来自调用方参数）
            force_refresh: 是否强制刷新缓存

        Returns:
            - None: 无可用工具（未配置/未启用/加载失败）
            - List[Dict]: OpenAI格式的工具列表
        """
        # 前置条件检查
        if not self._enable_mcp:
            logger.debug('🔧 MCP工具未启用 (_enable_mcp=False)')
            # 即使有缓存也清理掉，确保不使用
            self._cached_tools = None
            self._tools_loaded = False
            return None

        if not auto_mcp:
            logger.debug('🔧 auto_mcp=False，跳过MCP工具加载')
            # 即使有缓存也清理掉，确保不使用
            self._cached_tools = None
            self._tools_loaded = False
            return None

        if not self.user_id:
            logger.debug('🔧 MCP工具加载跳过: user_id未设置')
            return None

        if not self.db_session:
            logger.debug('🔧 MCP工具加载跳过: db_session未设置')
            return None

        # 使用缓存（只有 enable_mcp=True 时才使用缓存）
        if self._tools_loaded and not force_refresh:
            if self._cached_tools:
                logger.debug(f'🔧 使用缓存的MCP工具 ({len(self._cached_tools)}个)')
            return self._cached_tools

        try:
            from app.services.core.mcp_tools_loader import mcp_tools_loader

            self._cached_tools = await mcp_tools_loader.get_user_tools(
                user_id=self.user_id, db_session=self.db_session, use_cache=True, force_refresh=force_refresh
            )
            self._tools_loaded = True

            if self._cached_tools:
                logger.info(f'🔧 已加载 {len(self._cached_tools)} 个MCP工具')
            else:
                logger.debug(f'📭 用户 {self.user_id} 没有可用的MCP工具')

            return self._cached_tools

        except Exception as e:
            logger.warning(f'⚠️ 加载MCP工具失败: {e}')
            self._tools_loaded = True
            self._cached_tools = None
            # 工具加载失败时抛异常，而非静默返回 None（防止用户有工具但被忽略）
            raise RuntimeError(f'MCP工具加载失败: {e}') from e

    async def _handle_tool_calls(self, original_prompt: str, response: dict[str, Any], max_rounds: int = 2, **kwargs) -> dict[str, Any]:
        """
        处理AI返回的工具调用（支持 MCP 和 PM 工具）

        Args:
            original_prompt: 原始提示词
            response: AI响应（包含tool_calls）
            max_rounds: 最大工具调用轮数
            **kwargs: 传递给generate_text的其他参数

        Returns:
            最终的AI响应
        """
        from app.mcp import mcp_client

        tool_calls = response.get('tool_calls', [])
        if not tool_calls or not self.user_id:
            return response

        tool_metrics = ToolCallMetrics()
        tool_metrics.usage.add(TokenUsage.from_response(response))

        result = {
            'content': response.get('content', ''),
            'tool_calls_made': 0,
            'tools_used': [],
            'finish_reason': response.get('finish_reason', ''),
            'mcp_enhanced': True,
            'usage': response.get('usage'),
        }

        prompt = original_prompt

        for round_num in range(max_rounds):
            logger.info(f'🔧 工具调用 - 第{round_num + 1}/{max_rounds}轮，{len(tool_calls)}个工具')
            tool_metrics.mcp_rounds += 1

            # 分离 MCP 工具和 PM 工具
            mcp_tool_calls = [tc for tc in tool_calls if not tc['function']['name'].startswith('pm_')]
            pm_tool_calls = [tc for tc in tool_calls if tc['function']['name'].startswith('pm_')]

            tool_results = []

            # 执行 MCP 工具
            if mcp_tool_calls:
                try:
                    mcp_results = await mcp_client.batch_call_tools(user_id=self.user_id, tool_calls=mcp_tool_calls)
                    tool_results.extend(mcp_results)
                except Exception as e:
                    logger.error(f'❌ MCP工具调用失败: {e}')

            # 执行 PM 工具
            if pm_tool_calls:
                try:
                    tool_results.extend(await _execute_pm_tools(self, pm_tool_calls))
                except Exception as e:
                    logger.error(f'❌ PM工具调用失败: {e}')

            # 记录使用的工具
            for tc in tool_calls:
                name = tc['function']['name']
                tool_metrics.add_tool_name(name)
                if name not in result['tools_used']:
                    result['tools_used'].append(name)
            result['tool_calls_made'] += len(tool_calls)
            tool_metrics.tool_calls_count += len(tool_calls)

            # 构建工具上下文
            tool_context = mcp_client.build_tool_context(tool_results, format='markdown')

            # 更新提示词
            if round_num == max_rounds - 1:
                prompt = f'{original_prompt}\n\n{tool_context}\n\n⚠️ 重要：请基于以上工具查询结果，给出完整详细的最终答案。不要再调用工具。'
                tool_choice = 'none'
            else:
                prompt = f'{original_prompt}\n\n{tool_context}\n\n请基于以上工具查询结果，继续完成任务。'
                tool_choice = kwargs.get('tool_choice', 'auto')

            # 继续调用AI（保留 extra_tools）
            extra_tools = kwargs.get('extra_tools') or []
            tools_for_next = None if tool_choice == 'none' else extra_tools
            prov = self._get_provider(kwargs.get('provider'))
            next_response = await prov.generate(
                prompt=prompt,
                model=kwargs.get('model') or self.default_model,
                temperature=kwargs.get('temperature') or self.default_temperature,
                max_tokens=kwargs.get('max_tokens') or self.default_max_tokens,
                system_prompt=kwargs.get('system_prompt') or self.default_system_prompt,
                tools=tools_for_next,
                tool_choice=tool_choice,
            )
            tool_metrics.usage.add(TokenUsage.from_response(next_response))

            tool_calls = next_response.get('tool_calls', [])

            if not tool_calls:
                result['content'] = next_response.get('content', '')
                result['finish_reason'] = next_response.get('finish_reason', 'stop')
                result['usage'] = {
                    'prompt_tokens': tool_metrics.usage.prompt_tokens,
                    'completion_tokens': tool_metrics.usage.completion_tokens,
                    'total_tokens': tool_metrics.usage.total_tokens,
                }
                break

        result['__tool_metrics'] = tool_metrics
        return result

    async def generate_text(
        self,
        prompt: str,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        auto_mcp: bool = False,
        handle_tool_calls: bool = True,
        mcp_max_rounds: int | None = None,
        extra_tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        生成文本（自动支持MCP工具 + 额外工具）

        Args:
            prompt: 用户提示词
            provider: AI提供商
            model: 模型名称
            temperature: 温度
            max_tokens: 最大令牌数
            system_prompt: 系统提示词
            tools: 手动指定的工具列表（优先级高于自动加载）
            tool_choice: 工具选择策略
            auto_mcp: 是否自动加载MCP工具（默认True）
            handle_tool_calls: 是否自动处理工具调用（默认True）
            mcp_max_rounds: 最大工具调用轮数（None使用默认值3）
            extra_tools: 额外工具列表（如PM工具，OpenAI function格式）

        Returns:
            包含生成内容的字典
        """
        # 使用全局配置的MCP轮数（如果未指定）
        if mcp_max_rounds is None:
            mcp_max_rounds = app_settings.mcp_max_rounds

        # 合并 extra_tools
        if extra_tools:
            if tools is None:
                tools = []
            tools = tools + extra_tools

        # 自动加载MCP工具
        if auto_mcp and tools is None:
            tools = await self._prepare_mcp_tools(auto_mcp=auto_mcp)

        metrics = self._build_call_metrics(
            request_mode='文本',
            provider=provider,
            model=model,
            prompt=prompt,
            auto_mcp=auto_mcp,
            tools_count=len(tools) if tools else 0,
            stream=False,
        )

        try:
            prov = self._get_provider(provider)
            response = await prov.generate(
                prompt=prompt,
                model=model or self.default_model,
                temperature=temperature or self.default_temperature,
                max_tokens=max_tokens or self.default_max_tokens,
                system_prompt=system_prompt or self.default_system_prompt,
                tools=tools,
                tool_choice=tool_choice,
            )
            usage = TokenUsage.from_response(response)

            # 处理工具调用
            if handle_tool_calls and response.get('tool_calls'):
                response = await self._handle_tool_calls(
                    original_prompt=prompt,
                    response=response,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    tool_choice=tool_choice,
                    max_rounds=mcp_max_rounds,
                    extra_tools=extra_tools,
                )
                usage = TokenUsage.from_response(response)
                tool_metrics = response.get('__tool_metrics')
                if tool_metrics:
                    metrics.merge_tool_metrics(tool_metrics)

            metrics.finish(
                success=True,
                response_length=len(response.get('content', '') or ''),
                finish_reason=response.get('finish_reason'),
                usage=usage,
            )
            self._log_call_metrics(metrics)
            return response
        except Exception as e:
            metrics.finish(success=False, error=e)
            self._log_call_metrics(metrics)
            raise

    async def generate_text_stream(
        self,
        prompt: str,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        tool_choice: str | None = None,
        auto_mcp: bool = False,
        mcp_max_rounds: int | None = None,
        stop: list | None = None,
        on_complete: Callable | None = None,  # 回调：stream结束后收到finish_reason和usage
    ) -> AsyncGenerator[str, None]:
        """
        流式生成文本（自动支持MCP工具）

        工具调用在 Provider 层通过流式方式处理，支持真正的流式工具调用。

        Args:
            prompt: 用户提示词
            provider: AI提供商
            model: 模型名称
            temperature: 温度
            max_tokens: 最大令牌数
            system_prompt: 系统提示词
            tool_choice: 工具选择策略（"auto"/"none"/"required"）
            auto_mcp: 是否自动加载MCP工具
            mcp_max_rounds: 最大工具调用轮数（None使用默认值3）

        Yields:
            生成的文本块
        """
        logger.debug(f'🔧 generate_text_stream: auto_mcp={auto_mcp}, tool_choice={tool_choice}')

        tools_to_use = None

        # 加载MCP工具
        if auto_mcp:
            tools_to_use = await self._prepare_mcp_tools(auto_mcp=auto_mcp)
            if tools_to_use:
                logger.info(f'🔧 已获取 {len(tools_to_use)} 个MCP工具')

        metrics = self._build_call_metrics(
            request_mode='流式文本',
            provider=provider,
            model=model,
            prompt=prompt,
            auto_mcp=auto_mcp,
            tools_count=len(tools_to_use) if tools_to_use else 0,
            stream=True,
        )
        response_parts: list[str] = []
        latest_usage = TokenUsage()
        finish_reason = 'stop'

        try:
            # 流式生成（Provider 层处理工具调用）
            prov = self._get_provider(provider)
            logger.debug(f'🔧 开始流式生成，provider={provider or self.api_provider}, tools_count={len(tools_to_use) if tools_to_use else 0}')
            async for chunk in prov.generate_stream(
                prompt=prompt,
                model=model or self.default_model,
                temperature=temperature or self.default_temperature,
                max_tokens=max_tokens or self.default_max_tokens,
                system_prompt=system_prompt or self.default_system_prompt,
                tools=tools_to_use,
                tool_choice=tool_choice,
                user_id=self.user_id,
                stop=stop,
            ):
                if isinstance(chunk, dict):
                    content_str = chunk.get('content')
                    logger.warning(f'[DEBUG chunk] dict type={type(content_str)}, content={repr(content_str[:50]) if content_str else "EMPTY/FALSY"}')
                    if content_str:
                        metrics.mark_first_chunk()
                        metrics.chunk_count += 1
                        response_parts.append(content_str)
                        yield content_str
                    if chunk.get('usage'):
                        latest_usage = TokenUsage.from_response({'usage': chunk.get('usage')})
                    if chunk.get('finish_reason'):
                        finish_reason = chunk.get('finish_reason') or finish_reason
                    continue

                if chunk:
                    metrics.mark_first_chunk()
                    metrics.chunk_count += 1
                    response_parts.append(chunk)
                yield chunk

            metrics.finish(
                success=True,
                response_length=len(''.join(response_parts)),
                finish_reason=finish_reason,
                usage=latest_usage,
            )
            self._log_call_metrics(metrics)
            if on_complete:
                on_complete(finish_reason, latest_usage)
        except Exception as e:
            metrics.finish(
                success=False,
                response_length=len(''.join(response_parts)),
                finish_reason=finish_reason,
                usage=latest_usage,
                error=e,
            )
            self._log_call_metrics(metrics)
            raise
        except GeneratorExit:
            # GeneratorExit is not a subclass of Exception
            metrics.finish(
                success=False,
                response_length=len(''.join(response_parts)),
                finish_reason=finish_reason,
                usage=latest_usage,
                error=Exception('流式生成被中断(GeneratorExit)'),
            )
            self._log_call_metrics(metrics)
            raise

    async def call_with_json_retry(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_retries: int = 3,
        temperature: float | None = None,
        max_tokens: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        expected_type: str | None = None,
        auto_mcp: bool = False,
    ) -> dict | list:
        """
        带重试的 JSON 调用（自动支持MCP工具）

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            max_retries: 最大重试次数
            temperature: 温度
            max_tokens: 最大令牌数
            provider: AI提供商
            model: 模型名称
            expected_type: 期望的返回类型（"object"或"array"）
            auto_mcp: 是否自动加载MCP工具

        Returns:
            解析后的JSON数据
        """
        last_response = ''
        aggregate_usage = TokenUsage()
        metrics = self._build_call_metrics(
            request_mode='JSON重试',
            provider=provider,
            model=model,
            prompt=prompt,
            auto_mcp=auto_mcp,
            tools_count=0,
            stream=False,
        )

        try:
            for attempt in range(1, max_retries + 1):
                current_prompt = prompt if attempt == 1 else self._add_json_hint(prompt, last_response, attempt)

                result = await self.generate_text(
                    prompt=current_prompt,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    auto_mcp=auto_mcp,
                    handle_tool_calls=True,
                )
                aggregate_usage.add(TokenUsage.from_response(result))
                metrics.retry_count = attempt
                metrics.tools_count = max(metrics.tools_count, len(self._cached_tools) if self._cached_tools else 0)

                last_response = result.get('content', '')

                try:
                    data = parse_json(last_response)
                    if expected_type == 'object' and not isinstance(data, dict):
                        raise ValueError('期望对象')
                    if expected_type == 'array' and not isinstance(data, list):
                        raise ValueError('期望数组')
                    metrics.json_parse_success = True
                    metrics.finish(
                        success=True,
                        response_length=len(last_response),
                        finish_reason=result.get('finish_reason'),
                        usage=aggregate_usage,
                    )
                    self._log_call_metrics(metrics, title='AI调用汇总')
                    return data
                except Exception as e:
                    metrics.json_parse_success = False
                    if attempt == max_retries:
                        raise ValueError(f'JSON 解析失败: {e}') from e

            raise ValueError('JSON 调用失败')
        except Exception as e:
            metrics.finish(
                success=False,
                response_length=len(last_response),
                usage=aggregate_usage,
                error=e,
            )
            self._log_call_metrics(metrics, title='AI调用汇总')
            raise

    @staticmethod
    def _add_json_hint(prompt: str, failed: str, attempt: int) -> str:
        return f'{prompt}\n\n⚠️ 第{attempt}次重试，请返回纯JSON，不要markdown包裹。上次错误: {failed[:200]}...'

    @staticmethod
    def _clean_json_response(text: str) -> str:
        """清洗 JSON 响应"""
        return clean_json_response(text)


def create_user_ai_service(
    api_provider: str,
    api_key: str,
    api_base_url: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    system_prompt: str | None = None,
) -> AIService:
    """创建用户 AI 服务（不带MCP支持）"""
    return AIService(
        api_provider=api_provider,
        api_key=api_key,
        api_base_url=api_base_url,
        default_model=model_name,
        default_temperature=temperature,
        default_max_tokens=max_tokens,
        default_system_prompt=system_prompt,
    )


def create_user_ai_service_with_mcp(
    api_provider: str,
    api_key: str,
    api_base_url: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    user_id: str,
    db_session,
    system_prompt: str | None = None,
    enable_mcp: bool = True,
) -> AIService:
    """
    创建支持MCP的用户AI服务

    Args:
        api_provider: AI提供商
        api_key: API密钥
        api_base_url: API基础URL
        model_name: 模型名称
        temperature: 温度
        max_tokens: 最大令牌数
        user_id: 用户ID（用于加载MCP工具）
        db_session: 数据库会话
        system_prompt: 系统提示词
        enable_mcp: 是否启用MCP工具

    Returns:
        配置好的AIService实例
    """
    return AIService(
        api_provider=api_provider,
        api_key=api_key,
        api_base_url=api_base_url,
        default_model=model_name,
        default_temperature=temperature,
        default_max_tokens=max_tokens,
        default_system_prompt=system_prompt,
        user_id=user_id,
        db_session=db_session,
        enable_mcp=enable_mcp,
    )
