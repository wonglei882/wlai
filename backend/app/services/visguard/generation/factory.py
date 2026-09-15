"""生成器工厂 — 按配置返回生成器实例（GENERATE_BACKEND=none 时返回 None）。"""

import logging

from app.config import settings
from app.services.visguard.core.exceptions import BackendNotConfiguredError
from app.services.visguard.generation.base import BaseGenerator, GenerationParams

logger = logging.getLogger(__name__)


class _NotImplementedCloudGenerator(BaseGenerator):
    """云端生成器占位骨架：Phase C 落地真实适配器前保持行为明确。"""

    backend_name = 'cloud-standby'

    async def generate(self, params: GenerationParams):  # pragma: no cover - 占位实现
        raise BackendNotConfiguredError(
            detail='云端生图适配器尚未落地（Phase C）'
        )


def create_generator(
    backend: str | None = None,
    provider: str | None = None,
) -> BaseGenerator | None:
    """创建生成器实例。

    Args:
        backend: generate 后端名；缺省取 settings.visguard_generate_backend。
        provider: 云端供应商；缺省取 settings.visguard_cloud_provider。

    Returns:
        BaseGenerator | None: 'none' 时返回 None；'cloud' 时返回占位骨架。

    Raises:
        BackendNotConfiguredError: 未知后端名。
    """
    backend = (backend or settings.visguard_generate_backend).strip().lower()
    provider = provider or settings.visguard_cloud_provider

    if backend == 'none':
        return None
    if backend == 'cloud':
        logger.info('[VisGuard] 使用云端生成器（%s，占位骨架）', provider or '未指定供应商')
        return _NotImplementedCloudGenerator()
    raise BackendNotConfiguredError(detail=f'未知生图后端: {backend}')