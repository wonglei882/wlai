"""即梦 (Jimeng) 适配器（桩实现）。"""

from typing import Any

from app.services.comic.generators.base import GenerationAdapter, register_generator

import logging

logger = logging.getLogger(__name__)


@register_generator('jimeng')
class JimengAdapter(GenerationAdapter):
    """即梦出图/视频适配器。"""

    platform = 'jimeng'

    async def generate_image(self, prompt: str, negative_prompt: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        logger.info('[即梦] 生成图片: %s...', prompt[:80])
        return {
            'image_url': '',
            'seed': (params or {}).get('seed', 0),
            'parameters': {'platform': 'jimeng', 'prompt': prompt},
            'status': 'not_implemented',
            'message': '即梦 API 尚未接入，需要配置 JIMENG_API_KEY',
        }

    async def generate_video(self, image_url: str, prompt: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        logger.info('[即梦] 图生视频: %s', image_url[:80] if image_url else '')
        return {
            'video_url': '',
            'status': 'not_implemented',
            'message': '即梦 API 尚未接入',
        }
