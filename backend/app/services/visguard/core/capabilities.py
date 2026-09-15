"""VisGuard 能力矩阵推导。

设计意图（替代全局 mode 的一维建模）：
- 每个能力（embedding/preprocess/generate/inspect）独立选后端，互不耦合。
- 能力发现 API（GET /api/v1/visguard/capabilities）据此动态返回可用能力，
  前端按能力渲染 UI，不猜配置。
- 代码中不再出现 `if mode == 'hybrid'` 这类穷举判断，只按单能力 backend 分支。
"""

from dataclasses import dataclass, field

from app.config import settings

# 本地可用预处理器（controlnet_aux，排除 mediapipe 依赖的 openpose）
_LOCAL_PREPROCESSORS = ['lineart', 'canny', 'depth']


@dataclass
class Capabilities:
    """当前运行时的能力集合。"""

    embedding: bool = True
    preprocess: list[str] = field(default_factory=list)  # 可用预处理器类型
    generate: bool = False
    inspect: bool = False
    inspect_backend: str = ''  # 'local' | 'cloud' | ''


def is_visguard_enabled() -> bool:
    """任一能力后端非 'none' 即视为启用。"""
    return any(
        b.strip().lower() != 'none'
        for b in (
            settings.visguard_embedding_backend,
            settings.visguard_preprocess_backend,
            settings.visguard_generate_backend,
            settings.visguard_inspect_backend,
        )
    )


def get_backend(capability: str) -> str:
    """返回指定能力的后端名（embedding/preprocess/generate/inspect）。"""
    table = {
        'embedding': settings.visguard_embedding_backend,
        'preprocess': settings.visguard_preprocess_backend,
        'generate': settings.visguard_generate_backend,
        'inspect': settings.visguard_inspect_backend,
    }
    if capability not in table:
        raise ValueError(f'未知能力: {capability}')
    return table[capability].strip().lower()


def supported_preprocessors(backend: str) -> list[str]:
    """按后端推导支持的预处理器列表。"""
    backend = backend.strip().lower()
    if backend == 'local':
        return list(_LOCAL_PREPROCESSORS)
    if backend == 'cloud':
        # 延迟导入避免循环依赖（generation.capabilities 不依赖本模块）
        from app.services.visguard.generation.capabilities import (
            get_provider_capabilities,
        )

        caps = get_provider_capabilities(settings.visguard_cloud_provider)
        return list(caps.controlnet_types)
    return []


def get_capabilities() -> Capabilities:
    """从配置推导运行时能力。"""
    caps = Capabilities()
    caps.embedding = get_backend('embedding') != 'none'
    caps.preprocess = supported_preprocessors(get_backend('preprocess'))
    caps.generate = get_backend('generate') == 'cloud'
    caps.inspect = get_backend('inspect') in ('local', 'cloud')
    caps.inspect_backend = get_backend('inspect') if caps.inspect else ''
    return caps