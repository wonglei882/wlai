"""VisGuard 生成侧（云端生图）模块。

本轮落地供应商能力矩阵、生成器抽象与工厂骨架；
真实云端 API 适配（sansi/aliyun/tencent）在 Phase C 实现。
"""

from app.services.visguard.generation.base import BaseGenerator, GenerationParams
from app.services.visguard.generation.capabilities import (
    PRODUCER_CAPABILITIES,
    ProviderCapabilities,
    get_provider_capabilities,
    validate_generation_params,
)
from app.services.visguard.generation.factory import create_generator

__all__ = [
    'BaseGenerator',
    'GenerationParams',
    'ProviderCapabilities',
    'PRODUCER_CAPABILITIES',
    'get_provider_capabilities',
    'validate_generation_params',
    'create_generator',
]