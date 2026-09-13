"""多模态服务工厂 — 根据配置创建对应的多模态后端。

使用方式:
    from app.services.multimodal import get_multimodal_service

    mm = get_multimodal_service()
    result = await mm.analyze_image(image_url)

配置:
    MULTIMODAL_BACKEND=none|cloud|local  （环境变量或 .env）
"""

import logging
from typing import Optional

from app.services.multimodal.base import BaseMultimodalBackend, VisionResult
from app.services.multimodal.none_backend import NoneMultimodalBackend

logger = logging.getLogger(__name__)

# 单例缓存
_instance: Optional[BaseMultimodalBackend] = None


def get_multimodal_service() -> BaseMultimodalBackend:
    """获取多模态服务单例（根据配置自动选择后端）。

    Returns:
        BaseMultimodalBackend: 对应后端的实例
    """
    global _instance
    if _instance is not None:
        return _instance

    from app.config import settings

    backend_type = settings.multimodal_backend.lower().strip()

    if backend_type == 'cloud':
        from app.services.multimodal.cloud_backend import CloudMultimodalBackend
        _instance = CloudMultimodalBackend(
            provider=settings.multimodal_cloud_provider,
            model=settings.multimodal_cloud_model,
        )
        logger.info('[Multimodal] 使用云端后端: %s/%s', settings.multimodal_cloud_provider, settings.multimodal_cloud_model)

    elif backend_type == 'local':
        from app.services.multimodal.local_backend import LocalMultimodalBackend
        _instance = LocalMultimodalBackend(
            model_name=settings.multimodal_local_model,
            device=settings.multimodal_local_device,
        )
        logger.info('[Multimodal] 使用本地后端: %s → %s', settings.multimodal_local_model, settings.multimodal_local_device)

    else:
        _instance = NoneMultimodalBackend()
        if backend_type != 'none':
            logger.warning('[Multimodal] 未知后端类型: %s，回退到 none', backend_type)
        else:
            logger.info('[Multimodal] 多模态已禁用')

    return _instance


def reset_multimodal_service():
    """重置单例（测试用）。"""
    global _instance
    _instance = None


__all__ = [
    'get_multimodal_service',
    'reset_multimodal_service',
    'BaseMultimodalBackend',
    'VisionResult',
    'NoneMultimodalBackend',
]
