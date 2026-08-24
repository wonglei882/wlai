"""AI Provider 基类"""

from abc import ABC, abstractmethod
from typing import Any
from collections.abc import AsyncGenerator


class BaseAIProvider(ABC):
    """AI 提供商抽象基类"""

    @abstractmethod
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
        """生成文本"""
        pass

    @abstractmethod
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
        """流式生成"""
        pass
