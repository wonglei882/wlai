"""生成工具适配器基类 — 统一定义出图/视频/配音接口。

新增平台只需继承 GenerationAdapter 并注册到 GENERATOR_REGISTRY。
"""

from abc import ABC, abstractmethod
from typing import Any

import logging

logger = logging.getLogger(__name__)

# 注册表：platform_name -> GenerationAdapter 实例
GENERATOR_REGISTRY: dict[str, 'GenerationAdapter'] = {}


def register_generator(platform: str):
    """生成器注册装饰器。"""
    def decorator(cls):
        instance = cls()
        GENERATOR_REGISTRY[platform] = instance
        logger.info('注册生成器: %s', platform)
        return cls
    return decorator


class GenerationAdapter(ABC):
    """生成工具适配器 — 统一接口。"""

    platform: str = ''

    @abstractmethod
    async def generate_image(self, prompt: str, negative_prompt: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        """生成图片。

        Returns:
            {'image_url': str, 'seed': int, 'parameters': dict}
        """
        ...

    @abstractmethod
    async def generate_video(self, image_url: str, prompt: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        """图生视频。

        Returns:
            {'video_url': str, 'duration': float, 'parameters': dict}
        """
        ...

    async def generate_voice(self, text: str, voice_id: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        """文字转语音（可选实现）。

        Returns:
            {'audio_url': str, 'duration': float}
        """
        raise NotImplementedError(f'{self.platform} 不支持配音')

    async def check_status(self, task_id: str) -> dict[str, Any]:
        """查询异步生成任务状态（可选实现）。"""
        return {'status': 'unknown'}
