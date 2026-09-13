"""生成器基类与结果模型。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationResult:
    """一次生成的结果。"""

    url: str                      # 素材访问 URL / 文件路径
    file_path: str = ''           # 本地文件路径（如有）
    media_type: str = 'image'     # image / video / voice
    prompt_used: str = ''         # 实际使用的提示词
    parameters: dict[str, Any] = field(default_factory=dict)
    backend: str = 'mock'         # 实际生成后端标识


class BaseGenerator(ABC):
    """生成器基类。"""

    backend_name: str = 'base'

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> GenerationResult:
        """执行一次生成。prompt 为编译后的完整提示词。"""


class ImageGenerator(BaseGenerator):
    """图片生成器。"""

    backend_name = 'image'


class VideoGenerator(BaseGenerator):
    """视频生成器。"""

    backend_name = 'video'


class VoiceGenerator(BaseGenerator):
    """配音生成器。"""

    backend_name = 'voice'
