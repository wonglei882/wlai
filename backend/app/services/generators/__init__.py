"""生成器抽象层 — AI 内容生成器统一接口。

产品化策略：漫剧制片流水线只依赖抽象接口，具体平台（即梦/可灵/本地 SD）通过 factory 注入。
当前内置 Mock 实现（离线可跑通全流程），接入真实平台时实现对应子类并注册到 factory 即可。
"""

from .base import (
    BaseGenerator,
    GenerationResult,
    ImageGenerator,
    VideoGenerator,
    VoiceGenerator,
)
from .factory import get_image_generator, get_video_generator, get_voice_generator

__all__ = [
    'BaseGenerator',
    'GenerationResult',
    'ImageGenerator',
    'VideoGenerator',
    'VoiceGenerator',
    'get_image_generator',
    'get_video_generator',
    'get_voice_generator',
]
