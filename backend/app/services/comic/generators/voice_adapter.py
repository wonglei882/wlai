"""配音适配器（桩实现）— 剪映/ElevenLabs/GPT-SoVITS。"""

from typing import Any

from app.services.comic.generators.base import GenerationAdapter, register_generator

import logging

logger = logging.getLogger(__name__)


@register_generator('voice')
class VoiceAdapter(GenerationAdapter):
    """配音适配器 — 统一 TTS 接口。"""

    platform = 'voice'

    async def generate_image(self, prompt: str, negative_prompt: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {'status': 'not_supported', 'message': '配音适配器不支持出图'}

    async def generate_video(self, image_url: str, prompt: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {'status': 'not_supported', 'message': '配音适配器不支持视频'}

    async def generate_voice(self, text: str, voice_id: str = '', params: dict[str, Any] | None = None) -> dict[str, Any]:
        """文字转语音。

        [Milestone] 接入实际 TTS 服务：剪映（开发中）/ ElevenLabs / GPT-SoVITS 时间表待定
        """
        p = params or {}
        logger.info('[配音] TTS: %s... (voice=%s)', text[:50], voice_id)
        return {
            'audio_url': '',
            'duration': 0.0,
            'status': 'not_implemented',
            'message': 'TTS 服务尚未接入，支持剪映/ElevenLabs/GPT-SoVITS',
        }
