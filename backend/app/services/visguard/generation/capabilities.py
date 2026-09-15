"""供应商能力矩阵 — 每家云端出图供应商的能力声明。

用途：
- 能力发现 API 返回生成侧可用能力（controlnet 类型 / IP-Adapter 类型等）。
- validate_generation_params 在请求前按矩阵校验/降级参数，返回警告而非硬失败。
- 成本估算（price_per_image）供预算面板展示。

注意：矩阵只描述"能做什么"，不含 API 密钥与调用逻辑（Phase C 落适配器）。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderCapabilities:
    """供应商能力声明。"""

    provider_id: str
    controlnet_types: list[str] = field(default_factory=list)
    supports_ip_adapter: bool = False
    ip_adapter_types: list[str] = field(default_factory=list)
    supports_negative_prompt: bool = True
    supports_seed: bool = True
    supports_async: bool = False
    max_resolution: int = 1024
    price_per_image: float = 0.1


PRODUCER_CAPABILITIES: dict[str, ProviderCapabilities] = {
    'sansi': ProviderCapabilities(
        provider_id='sansi',
        controlnet_types=['canny', 'lineart', 'depth', 'openpose', 'scribble'],
        supports_ip_adapter=True,
        ip_adapter_types=['style', 'face', 'garment', 'fusion'],
        supports_negative_prompt=True,
        supports_seed=True,
        supports_async=True,
        max_resolution=2048,
        price_per_image=0.10,
    ),
    'aliyun': ProviderCapabilities(
        provider_id='aliyun',
        controlnet_types=['canny', 'lineart', 'depth'],
        supports_ip_adapter=True,
        ip_adapter_types=['style', 'face'],
        supports_negative_prompt=True,
        supports_seed=False,
        supports_async=True,
        max_resolution=1024,
        price_per_image=0.15,
    ),
    'tencent': ProviderCapabilities(
        provider_id='tencent',
        controlnet_types=['canny', 'lineart'],
        supports_ip_adapter=True,
        ip_adapter_types=['style'],
        supports_negative_prompt=True,
        supports_seed=True,
        supports_async=False,
        max_resolution=1024,
        price_per_image=0.08,
    ),
    'openai': ProviderCapabilities(
        provider_id='openai',
        controlnet_types=[],
        supports_ip_adapter=False,
        supports_negative_prompt=True,
        supports_seed=True,
        supports_async=False,
        max_resolution=1024,
        price_per_image=0.12,
    ),
}


def get_provider_capabilities(provider: str) -> ProviderCapabilities:
    """获取供应商能力；未知供应商返回保守默认（不崩溃）。"""
    key = (provider or '').strip().lower()
    return PRODUCER_CAPABILITIES.get(
        key, ProviderCapabilities(provider_id=key or 'unknown'),
    )


def validate_generation_params(provider: str, params: dict) -> list[str]:
    """按供应商矩阵校验/降级生图参数，返回警告列表（不修改调用方对象）。

    降级规则：
    - control_type 不受支持 → 降级为 'canny'（尽量保留结构控制意图）
    - ip_adapter_type 不受支持 → 移除该键
    - 供应商不支持 seed → 移除 seed 键
    """
    caps = get_provider_capabilities(provider)
    warnings: list[str] = []

    control_type = params.get('control_type')
    if control_type and control_type not in caps.controlnet_types:
        warnings.append(
            f'供应商 {provider} 不支持 control_type={control_type}，已降级为 canny'
        )
        params['control_type'] = 'canny'

    ip_type = params.get('ip_adapter_type')
    if ip_type and ip_type not in caps.ip_adapter_types:
        warnings.append(
            f'供应商 {provider} 不支持 ip_adapter_type={ip_type}，已忽略'
        )
        params.pop('ip_adapter_type', None)

    if 'seed' in params and not caps.supports_seed:
        warnings.append(f'供应商 {provider} 不支持 seed，已忽略')
        params.pop('seed', None)

    return warnings