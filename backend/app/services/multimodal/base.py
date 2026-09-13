"""多模态服务基类 — 定义视觉理解统一接口。

所有后端（cloud / local / none）继承此基类，
上层业务（视觉审核、角色一致性检测等）只依赖此接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import logging

logger = logging.getLogger(__name__)


@dataclass
class VisionResult:
    """视觉分析结果。"""

    description: str = ''  # 图片描述
    objects: list[dict[str, Any]] = field(default_factory=list)  # 检测到的对象
    consistency_score: float = 1.0  # 一致性得分 0.0-1.0
    issues: list[str] = field(default_factory=list)  # 发现的问题
    raw_response: str = ''  # 原始模型响应
    backend: str = 'none'  # 使用的后端


class BaseMultimodalBackend(ABC):
    """多模态后端抽象基类。"""

    backend_name: str = 'base'

    @abstractmethod
    async def analyze_image(
        self,
        image_url: str,
        prompt: str = '请详细描述这张图片中的角色外貌特征。',
    ) -> VisionResult:
        """分析单张图片。

        Args:
            image_url: 图片 URL 或 base64 data URI
            prompt: 分析提示词

        Returns:
            VisionResult
        """
        ...

    @abstractmethod
    async def compare_images(
        self,
        image_url_a: str,
        image_url_b: str,
        prompt: str = '对比这两张图片中同一角色的外貌，列出差异。',
    ) -> VisionResult:
        """对比两张图片的视觉一致性。

        Args:
            image_url_a: 第一张图片
            image_url_b: 第二张图片
            prompt: 对比提示词

        Returns:
            VisionResult（consistency_score 反映相似度）
        """
        ...

    async def describe_for_accessibility(self, image_url: str) -> str:
        """为图片生成无障碍描述（alt text）。默认调用 analyze_image。"""
        result = await self.analyze_image(image_url, '用一句话描述这张图片。')
        return result.description

    @property
    def is_available(self) -> bool:
        """当前后端是否可用。"""
        return True
