"""云端多模态后端 — 调用 OpenAI / Gemini / Anthropic 视觉 API。

复用项目已有的 ai_clients 层，无需额外依赖。
"""

from typing import Any

from app.services.multimodal.base import BaseMultimodalBackend, VisionResult
from app.services.json_helper import safe_json_loads

import logging

logger = logging.getLogger(__name__)


class CloudMultimodalBackend(BaseMultimodalBackend):
    """云端多模态后端。"""

    backend_name = 'cloud'

    def __init__(self, provider: str = 'openai', model: str = 'gpt-4o'):
        self.provider = provider
        self.model = model

    async def analyze_image(
        self,
        image_url: str,
        prompt: str = '请详细描述这张图片中的角色外貌特征。',
    ) -> VisionResult:
        """通过云端 API 分析图片。"""
        try:
            response_text = await self._call_vision_api(image_url, prompt)
            return VisionResult(
                description=response_text,
                raw_response=response_text,
                backend=f'cloud:{self.provider}/{self.model}',
            )
        except Exception as e:
            logger.error('[CloudMM] 图片分析失败: %s', e)
            return VisionResult(
                issues=[f'云端分析失败: {e}'],
                backend=f'cloud:{self.provider}/{self.model}',
            )

    async def compare_images(
        self,
        image_url_a: str,
        image_url_b: str,
        prompt: str = '对比这两张图片中同一角色的外貌，列出差异。请返回JSON: {"score": 0.0-1.0, "differences": [...]}',
    ) -> VisionResult:
        """通过云端 API 对比两张图片。"""
        try:
            response_text = await self._call_vision_api(
                [image_url_a, image_url_b],
                prompt,
            )
            # 尝试解析 JSON 响应
            parsed = safe_json_loads(response_text)
            score = 1.0
            differences = []
            if isinstance(parsed, dict):
                score = float(parsed.get('score', 1.0))
                differences = parsed.get('differences', [])

            return VisionResult(
                description=response_text,
                consistency_score=max(0.0, min(1.0, score)),
                issues=differences,
                raw_response=response_text,
                backend=f'cloud:{self.provider}/{self.model}',
            )
        except Exception as e:
            logger.error('[CloudMM] 图片对比失败: %s', e)
            return VisionResult(
                issues=[f'云端对比失败: {e}'],
                backend=f'cloud:{self.provider}/{self.model}',
            )

    async def _call_vision_api(self, images: str | list[str], prompt: str) -> str:
        """调用云端视觉 API。

        根据 provider 选择对应的客户端：
        - openai: OpenAI Chat Completions with image_url
        - gemini: Gemini generateContent with inline_data
        - anthropic: Anthropic Messages with base64 image
        """
        if isinstance(images, str):
            images = [images]

        if self.provider == 'openai':
            return await self._call_openai_vision(images, prompt)
        elif self.provider == 'gemini':
            return await self._call_gemini_vision(images, prompt)
        elif self.provider == 'anthropic':
            return await self._call_anthropic_vision(images, prompt)
        else:
            raise ValueError(f'不支持的多模态提供商: {self.provider}')

    async def _call_openai_vision(self, images: list[str], prompt: str) -> str:
        """OpenAI GPT-4o 视觉调用。"""
        from app.config import settings

        api_key = settings.openai_api_key
        base_url = settings.openai_base_url or 'https://api.openai.com/v1'
        if not api_key:
            raise ValueError('OPENAI_API_KEY 未配置')

        import httpx

        # 构建消息
        content = [{'type': 'text', 'text': prompt}]
        for img_url in images:
            content.append({
                'type': 'image_url',
                'image_url': {'url': img_url, 'detail': 'high'},
            })

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f'{base_url}/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': self.model,
                    'messages': [{'role': 'user', 'content': content}],
                    'max_tokens': 1024,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data['choices'][0]['message']['content']

    async def _call_gemini_vision(self, images: list[str], prompt: str) -> str:
        """Gemini 视觉调用（桩实现，复用 OpenAI 格式兼容层）。"""
        # TODO: 接入 Gemini 原生 API
        logger.warning('[CloudMM] Gemini 视觉尚未实现，回退到 OpenAI')
        return await self._call_openai_vision(images, prompt)

    async def _call_anthropic_vision(self, images: list[str], prompt: str) -> str:
        """Anthropic 视觉调用（桩实现）。"""
        # TODO: 接入 Anthropic 原生 API
        logger.warning('[CloudMM] Anthropic 视觉尚未实现，回退到 OpenAI')
        return await self._call_openai_vision(images, prompt)
