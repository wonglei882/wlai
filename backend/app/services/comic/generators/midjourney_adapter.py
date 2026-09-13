"""Midjourney 适配器（桩实现）。

实际接入需要 Midjourney API 密钥和调用逻辑。
"""

from typing import Any

from app.services.comic.generators.base import GenerationAdapter, register_generator

import logging

logger = logging.getLogger(__name__)


@register_generator('midjourney')
class MidjourneyAdapter(GenerationAdapter):
    """Midjourney 出图适配器。"""

    platform = 'midjourney'

    async def generate_image(self, prompt: str, negative_prompt: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用 Midjourney 生成图片。

        TODO: 接入实际 API
        """
        p = params or {}
        logger.info('[Midjourney] 生成图片: %s...', prompt[:80])
        # 桩实现：返回模拟结果
        return {
            'image_url': '',
            'seed': p.get('seed', 0),
            'parameters': {
                'platform': 'midjourney',
                'prompt': prompt,
                'ar': p.get('ar', '9:16'),
                'niji': p.get('niji', 6),
            },
            'status': 'not_implemented',
            'message': 'Midjourney API 尚未接入，需要配置 MJ_API_KEY',
        }

    async def generate_video(self, image_url: str, prompt: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Midjourney 不直接支持视频生成。"""
        return {
            'video_url': '',
            'status': 'not_supported',
            'message': 'Midjourney 不支持视频生成，请使用可灵/即梦',
        }
