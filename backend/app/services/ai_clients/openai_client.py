"""OpenAI 客户端"""

from app.core import json_utils as json
from typing import Any
from collections.abc import AsyncGenerator

from app.logger import get_logger
from .base_client import BaseAIClient

logger = get_logger(__name__)


class OpenAIClient(BaseAIClient):
    """OpenAI API 客户端"""

    def _build_headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

    def _build_payload(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: list | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
        stop: list | None = None,
    ) -> dict[str, Any]:
        """构建Payload

        Args:
            self:
            messages:
            model:
            temperature:
            max_tokens:
            tools:
            tool_choice:
            stream:
            stop:

        Returns:
            Dict[str, Any]
        """
        payload = {
            'model': model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        if stop:
            payload['stop'] = stop
        if stream:
            payload['stream'] = True
        if tools:
            # 清理 $schema 字段
            cleaned = []
            for t in tools:
                tc = t.copy()
                if 'function' in tc and 'parameters' in tc['function']:
                    tc['function']['parameters'] = {k: v for k, v in tc['function']['parameters'].items() if k != '$schema'}
                cleaned.append(tc)
            payload['tools'] = cleaned
            if tool_choice:
                payload['tool_choice'] = tool_choice
        return payload

    async def chat_completion(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: list | None = None,
        tool_choice: str | None = None,
        stop: list | None = None,
    ) -> dict[str, Any]:
        """对话Completion

        Args:
            self:
            messages:
            model:
            temperature:
            max_tokens:
            tools:
            tool_choice:
            stop:

        Returns:
            Dict[str, Any]
        """
        payload = self._build_payload(messages, model, temperature, max_tokens, tools, tool_choice, stop=stop)

        logger.debug(f'📤 OpenAI 请求 payload: {json.dumps(payload, ensure_ascii=False, indent=2)}')

        data = await self._request_with_retry('POST', '/chat/completions', payload)

        # 调试日志：输出原始响应
        logger.debug(f'📥 OpenAI 原始响应: {json.dumps(data, ensure_ascii=False, indent=2)}')

        choices = data.get('choices', [])
        if not choices or len(choices) == 0:
            raise ValueError('API 返回空 choices 或 choices 为空列表')

        choice = choices[0]
        message = choice.get('message', {})
        usage = data.get('usage') or {}
        return {
            'content': message.get('content', ''),
            'tool_calls': message.get('tool_calls'),
            'finish_reason': choice.get('finish_reason'),
            'usage': {
                'prompt_tokens': usage.get('prompt_tokens'),
                'completion_tokens': usage.get('completion_tokens'),
                'total_tokens': usage.get('total_tokens'),
            },
        }

    async def chat_completion_stream(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: list | None = None,
        tool_choice: str | None = None,
        stop: list | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        流式生成，支持工具调用

        Yields:
            Dict with keys:
            - content: str - 文本内容块
            - tool_calls: list - 工具调用列表（如果有）
            - done: bool - 是否结束
        """
        payload = self._build_payload(messages, model, temperature, max_tokens, tools, tool_choice, stream=True, stop=stop)

        tool_calls_buffer = {}  # 收集工具调用块

        try:
            async with await self._request_with_retry('POST', '/chat/completions', payload, stream=True) as response:
                response.raise_for_status()
                try:
                    async for line in response.aiter_lines():
                        if line.startswith('data: '):
                            data_str = line[6:]
                            if data_str.strip() == '[DONE]':
                                # 流结束，检查是否有工具调用需要处理
                                if tool_calls_buffer:
                                    yield {'tool_calls': list(tool_calls_buffer.values()), 'done': True}
                                yield {'done': True}
                                break
                            try:
                                data = json.loads(data_str)
                                choices = data.get('choices', [])
                                if choices and len(choices) > 0:
                                    delta = choices[0].get('delta', {})
                                    content = delta.get('content', '')

                                    # 检查工具调用
                                    tc_list = delta.get('tool_calls')
                                    if tc_list:
                                        for tc in tc_list:
                                            index = tc.get('index', 0)
                                            if index not in tool_calls_buffer:
                                                tool_calls_buffer[index] = tc
                                            else:
                                                existing = tool_calls_buffer[index]
                                                # 合并 function.arguments
                                                if 'function' in tc and 'function' in existing and tc['function'].get('arguments'):
                                                    existing['function']['arguments'] = (
                                                        existing['function'].get('arguments', '') + tc['function']['arguments']
                                                    )

                                    usage = data.get('usage')
                                    if usage:
                                        yield {
                                            'usage': {
                                                'prompt_tokens': usage.get('prompt_tokens'),
                                                'completion_tokens': usage.get('completion_tokens'),
                                                'total_tokens': usage.get('total_tokens'),
                                            }
                                        }

                                    if content:
                                        yield {'content': content}

                            except json.JSONDecodeError:
                                continue
                except GeneratorExit:
                    # 生成器被关闭，这是正常的清理过程
                    logger.warning('流式响应生成器被关闭(GeneratorExit)，流异常中断')
                    raise
                except Exception as iter_error:
                    logger.error(f'流式响应迭代出错: {str(iter_error)}')
                    raise
        except GeneratorExit:
            logger.warning('流式HTTP连接被关闭(GeneratorExit)')
            raise
        except Exception as e:
            logger.error(f'流式请求出错: {str(e)}')
            raise
