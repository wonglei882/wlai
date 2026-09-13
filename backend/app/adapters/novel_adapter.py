"""网文适配器 — 将网文章节内容映射为通用 ContentSegment。

桥接现有 Chapter 模型与通用 ContentSegment，
使现有巡检维度（角色/伏笔/世界观/大纲/质量/段落）可无缝运行。
"""

from typing import Any

from app.adapters.base import ContentAdapter, register_adapter
from app.models.content_segment import ContentSegment

import logging

logger = logging.getLogger(__name__)


@register_adapter('novel_chapter')
class NovelAdapter(ContentAdapter):
    """网文适配器 — 处理长篇小说章节内容。"""

    content_type = 'novel_chapter'

    async def ingest(
        self,
        raw_content: dict[str, Any],
        project_id: str,
        user_id: str,
    ) -> ContentSegment:
        """将网文章节推送转换为 ContentSegment。

        期望 raw_content 格式:
        {
            "sequence_number": 15,
            "title": "第十五章 暗流涌动",
            "content": "正文内容...",
            "metadata": {
                "characters": ["张三", "李四"],
                "location": "京城",
                "world_rules_hash": "abc123"
            }
        }
        """
        metadata = raw_content.get('metadata', {})

        segment = ContentSegment(
            project_id=project_id,
            user_id=user_id,
            content_type='novel_chapter',
            sequence_number=raw_content.get('sequence_number', 0),
            title=raw_content.get('title', ''),
            content=raw_content.get('content', ''),
            metadata_json={
                'characters': metadata.get('characters', []),
                'location': metadata.get('location', ''),
                'world_rules_hash': metadata.get('world_rules_hash', ''),
                'word_count': len(raw_content.get('content', '')),
            },
        )
        return segment

    async def extract_entities(self, segment: ContentSegment) -> dict[str, Any]:
        """从网文章节提取实体。"""
        meta = segment.metadata_json or {}
        return {
            'characters': meta.get('characters', []),
            'location': meta.get('location', ''),
            'world_rules_hash': meta.get('world_rules_hash', ''),
            'word_count': meta.get('word_count', 0),
        }

    def get_scan_dimensions(self) -> list[str]:
        """网文支持的扫描维度。"""
        return [
            'character_consistency',
            'foreshadow_age',
            'world_rule_drift',
            'outline_drift',
            'quality_score',
            'paragraph_format',
        ]

    def validate_input(self, raw_content: dict[str, Any]) -> tuple[bool, str]:
        """校验网文输入。"""
        if not raw_content.get('content'):
            return False, 'content 不能为空'
        if not raw_content.get('sequence_number'):
            return False, 'sequence_number（章节号）不能为空'
        return True, ''
