"""Anthropic Provider"""

from typing import Any
from collections.abc import AsyncGenerator

from app.logger import get_logger
from app.services.ai_clients.anthropic_client import AnthropicClient
from .base_provider import BaseAIProvider

logger = get_logger(__name__)


class AnthropicProvider(BaseAIProvider):
    """Anthropic 提供商"""

    def __init__(self, client: AnthropicClient):
        self.client = client

    async def generate(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        stop: list[str] | None = None,
    ) -> dict[str, Any]:
        """生成

        Args:
            self:
            prompt:
            model:
            temperature:
            max_tokens:
            system_prompt:
            tools:
            tool_choice:
            stop:

        Returns:
            Dict[str, Any]
        """
        messages = [{'role': 'user', 'content': prompt}]
        return await self.client.chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            tools=tools,
            tool_choice=tool_choice,
            stop_sequences=stop,
        )

    async def generate_stream(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        user_id: str | None = None,
        stop: list[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        # 如果有工具，使用真正的流式工具调用
        """生成流式

        Args:
            self:
            prompt:
            model:
            temperature:
            max_tokens:
            system_prompt:
            tools:
            tool_choice:
            user_id:
            stop:

        Returns:
            AsyncGenerator[str, None]
        """
        if tools:
            logger.debug(f'🔧 AnthropicProvider: 有 {len(tools)} 个工具，使用流式处理')
            messages = [{'role': 'user', 'content': prompt}]
            actual_tool_choice = tool_choice if tool_choice else 'auto'

            tool_calls_buffer = []

            async for chunk in self.client.chat_completion_stream(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                tools=tools,
                tool_choice=actual_tool_choice,
                stop_sequences=stop,
            ):
                # 检查是否有工具调用
                if chunk.get('tool_calls'):
                    tool_calls_buffer.extend(chunk['tool_calls'])
                    logger.debug(f'🔧 收到工具调用: {len(chunk["tool_calls"])} 个')

                # 检查是否结束
                if chunk.get('done'):
                    if tool_calls_buffer:
                        logger.info(f'🔧 流式结束，处理 {len(tool_calls_buffer)} 个工具调用')
                        from app.mcp import mcp_client

                        actual_user_id = user_id or ''
                        tool_results = await mcp_client.batch_call_tools(user_id=actual_user_id, tool_calls=tool_calls_buffer)
                        # 将工具结果注入到上下文中
                        tool_context = mcp_client.build_tool_context(tool_results, format='markdown')

                        # 构建最终提示词，要求AI基于工具结果回答
                        final_prompt = f'{prompt}\n\n{tool_context}\n\n请基于以上工具查询结果，给出完整详细的回答。'
                        final_messages = [{'role': 'user', 'content': final_prompt}]

                        # 递归调用生成最终结果（不传tools，禁止AI继续调用工具）
                        async for final_chunk in self._generate_with_tools(
                            final_messages,
                            model,
                            temperature,
                            max_tokens,
                            system_prompt,
                            tools=None,
                            user_id=user_id,
                            stop=stop,
                        ):
                            yield final_chunk
                    if chunk.get('finish_reason'):
                        yield {'finish_reason': chunk.get('finish_reason'), 'done': True}
                    break

                if chunk.get('usage'):
                    yield {'usage': chunk.get('usage')}

                # 输出文本内容
                if chunk.get('content'):
                    yield chunk['content']
            return

        # 无工具时普通流式生成
        messages = [{'role': 'user', 'content': prompt}]
        async for chunk in self.client.chat_completion_stream(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            stop_sequences=stop,
        ):
            if isinstance(chunk, dict):
                if chunk.get('usage'):
                    yield {'usage': chunk.get('usage')}
                if chunk.get('finish_reason'):
                    yield {'finish_reason': chunk.get('finish_reason')}
                if chunk.get('content'):
                    yield chunk['content']
            else:
                yield chunk

    async def _generate_with_tools(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str | None = None,
        tools: list = None,
        user_id: str | None = None,
        recursion_depth: int = 0,
        stop: list[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        """辅助方法：带工具的流式生成"""
        max_depth = 2  # 最多递归2层，防止无限工具循环

        if recursion_depth >= max_depth:
            # 达到递归上限，禁止使用工具，强制AI输出文本
            async for chunk in self.client.chat_completion_stream(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                stop_sequences=stop,
            ):
                if isinstance(chunk, dict):
                    if chunk.get('usage'):
                        yield {'usage': chunk.get('usage')}
                    if chunk.get('finish_reason'):
                        yield {'finish_reason': chunk.get('finish_reason')}
                    if chunk.get('content'):
                        yield chunk['content']
                else:
                    yield chunk
            return

        tool_calls_buffer = []

        async for chunk in self.client.chat_completion_stream(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            tools=tools,
            tool_choice='auto',
            stop_sequences=stop,
        ):
            if chunk.get('tool_calls'):
                tool_calls_buffer.extend(chunk['tool_calls'])
                logger.debug(f'🔧 _generate_with_tools 收到工具调用: {len(chunk["tool_calls"])} 个')

            if chunk.get('done'):
                if tool_calls_buffer:
                    from app.mcp import mcp_client

                    actual_user_id = user_id or ''
                    tool_results = await mcp_client.batch_call_tools(user_id=actual_user_id, tool_calls=tool_calls_buffer)
                    tool_context = mcp_client.build_tool_context(tool_results, format='markdown')

                    messages.append({'role': 'user', 'content': f'{tool_context}\n\n请基于以上工具查询结果，给出完整详细的回答。'})

                    # 递归时不再传递工具，防止无限工具循环
                    async for final_chunk in self._generate_with_tools(
                        messages,
                        model,
                        temperature,
                        max_tokens,
                        system_prompt,
                        tools=None,
                        user_id=user_id,
                        recursion_depth=recursion_depth + 1,
                        stop=stop,
                    ):
                        yield final_chunk
                if chunk.get('finish_reason'):
                    yield {'finish_reason': chunk.get('finish_reason'), 'done': True}
                break

            if chunk.get('usage'):
                yield {'usage': chunk.get('usage')}

            if chunk.get('content'):
                yield chunk['content']
