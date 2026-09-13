"""空多模态后端 — 禁用多模态时的占位实现。

所有方法返回空结果，不执行任何视觉分析。
适用于无 GPU、无云端 API key 的场景。
"""

from app.services.multimodal.base import BaseMultimodalBackend, VisionResult

import logging

logger = logging.getLogger(__name__)


class NoneMultimodalBackend(BaseMultimodalBackend):
    """空后端 — 多模态禁用。"""

    backend_name = 'none'

    @property
    def is_available(self) -> bool:
        return False

    async def analyze_image(self, image_url: str, prompt: str = '') -> VisionResult:
        logger.debug('[NoneMM] 多模态已禁用，跳过图片分析')
        return VisionResult(
            description='',
            issues=['多模态功能未启用（MULTIMODAL_BACKEND=none）'],
            backend='none',
        )

    async def compare_images(self, image_url_a: str, image_url_b: str, prompt: str = '') -> VisionResult:
        logger.debug('[NoneMM] 多模态已禁用，跳过图片对比')
        return VisionResult(
            description='',
            consistency_score=1.0,
            issues=['多模态功能未启用（MULTIMODAL_BACKEND=none）'],
            backend='none',
        )
