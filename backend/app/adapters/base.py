"""内容适配器抽象基类 — 定义领域内容到通用模型的映射接口。

设计参照量子算法项目 BaseAlgorithm 模式：
- 统一接口：ingest() / extract_entities() / get_scan_dimensions()
- 注册表驱动：ADAPTER_REGISTRY 按 content_type 索引
- 新增类型只需继承 + 实现 + 注册
"""

from abc import ABC, abstractmethod
from typing import Any

from app.models.content_segment import ContentSegment

import logging

logger = logging.getLogger(__name__)

# 适配器注册表：content_type -> ContentAdapter 实例
ADAPTER_REGISTRY: dict[str, 'ContentAdapter'] = {}


def register_adapter(content_type: str):
    """适配器注册装饰器。

    用法:
        @register_adapter('novel_chapter')
        class NovelAdapter(ContentAdapter):
            ...
    """

    def decorator(cls):
        instance = cls()
        if content_type in ADAPTER_REGISTRY:
            logger.warning(
                'ContentAdapter 重复注册: %s (已有 %s, 覆盖为 %s)',
                content_type,
                type(ADAPTER_REGISTRY[content_type]).__name__,
                cls.__name__,
            )
        ADAPTER_REGISTRY[content_type] = instance
        return cls

    return decorator


class ContentAdapter(ABC):
    """内容适配器抽象基类。

    子类必须实现:
        - content_type: 内容类型标识
        - ingest(): 将外部内容转换为 ContentSegment
        - extract_entities(): 从内容中提取实体
        - get_scan_dimensions(): 返回支持的扫描维度列表
    """

    content_type: str

    @abstractmethod
    async def ingest(
        self,
        raw_content: dict[str, Any],
        project_id: str,
        user_id: str,
    ) -> ContentSegment:
        """将外部推送内容转换为通用 ContentSegment。

        Args:
            raw_content: 外部系统推送的原始内容 dict
            project_id: 项目 ID
            user_id: 用户 ID

        Returns:
            ContentSegment 实例（未持久化）
        """
        ...

    @abstractmethod
    async def extract_entities(self, segment: ContentSegment) -> dict[str, Any]:
        """从 ContentSegment 中提取领域实体。

        Returns:
            实体字典，如:
            - 小说: {'characters': [...], 'location': '...', 'world_rules_hash': '...'}
            - 漫剧: {'characters_visual': [...], 'scene': '...'}
        """
        ...

    @abstractmethod
    def get_scan_dimensions(self) -> list[str]:
        """返回该领域支持的扫描维度列表。

        用于巡检时按项目类型选择扫描维度。
        """
        ...

    def validate_input(self, raw_content: dict[str, Any]) -> tuple[bool, str]:
        """校验输入内容是否满足该类型的最小要求。

        Returns:
            (is_valid, error_message)
        """
        return True, ''
