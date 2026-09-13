"""可灵 (Kling) 适配器（桩实现）。"""

from typing import Any

from app.services.comic.generators.base import GenerationAdapter, register_generator

import logging

logger = logging.getLogger(__name__)


@register_generator('kling')
class KlingAdapter(GenerationAdapter):
    """可灵视频生成适配器。"""

    platform = 'kling'

    async def generate_image(self, prompt: str, negative_prompt: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        logger.info('[可灵] 生成图片: %s...', prompt[:80])
        return {
            'image_url': '',
            'seed': (params or {}).get('seed', 0),
            'parameters': {'platform': 'kling', 'prompt': prompt},
            'status': 'not_implemented',
            'message': '可灵 API 尚未接入，需要配置 KLING_API_KEY',
        }

    async def generate_video(self, image_url: str, prompt: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        logger.info('[可灵] 图生视频: %s', image_url[:80] if image_url else '')
        return {
            'video_url': '',
            'status': 'not_implemented',
            'message': '可灵 API 尚未接入，需要配置 KLING_API_KEY',
        }
