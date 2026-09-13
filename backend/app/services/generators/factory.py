"""生成器工厂 — 根据 provider 选择实现。

配置来源：pm_features.yaml comic_production.generator；当前仅内置 mock。
接入真实平台（即梦/可灵/本地 SD）时：实现对应子类，注册到下方 _REGISTRY 并补配置分支。
"""

from .base import ImageGenerator, VideoGenerator, VoiceGenerator
from .mock import MockImageGenerator, MockVideoGenerator, MockVoiceGenerator

_IMAGE_REGISTRY: dict[str, type[ImageGenerator]] = {
    'mock': MockImageGenerator,
}
_VIDEO_REGISTRY: dict[str, type[VideoGenerator]] = {
    'mock': MockVideoGenerator,
}
_VOICE_REGISTRY: dict[str, type[VoiceGenerator]] = {
    'mock': MockVoiceGenerator,
}


def get_image_generator(provider: str | None = None) -> ImageGenerator:
    key = (provider or 'mock').lower()
    return _IMAGE_REGISTRY.get(key, MockImageGenerator)()


def get_video_generator(provider: str | None = None) -> VideoGenerator:
    key = (provider or 'mock').lower()
    return _VIDEO_REGISTRY.get(key, MockVideoGenerator)()


def get_voice_generator(provider: str | None = None) -> VoiceGenerator:
    key = (provider or 'mock').lower()
    return _VOICE_REGISTRY.get(key, MockVoiceGenerator)()
