"""内容适配器层 — 将领域特定内容映射为通用 ContentSegment。

适配器注册表（数据驱动）：
    ADAPTER_REGISTRY: dict[str, ContentAdapter]

新增内容类型只需实现 ContentAdapter 子类并注册。
"""

from app.adapters.base import ContentAdapter, ADAPTER_REGISTRY  # noqa: F401

# 导入适配器模块以触发注册
from app.adapters.novel_adapter import NovelAdapter  # noqa: F401
from app.adapters.comic_adapter import ComicAdapter  # noqa: F401

__all__ = ['ContentAdapter', 'ADAPTER_REGISTRY', 'NovelAdapter', 'ComicAdapter']
