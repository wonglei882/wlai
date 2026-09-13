"""漫剧适配器 — 将漫剧分镜内容映射为通用 ContentSegment。

处理漫剧分镜脚本推送，支持角色视觉一致性、场景连续性等维度。
"""

from typing import Any

from app.adapters.base import ContentAdapter, register_adapter
from app.models.content_segment import ContentSegment

import logging

logger = logging.getLogger(__name__)


@register_adapter('comic_panel')
class ComicAdapter(ContentAdapter):
    """漫剧适配器 — 处理分镜脚本内容。"""

    content_type = 'comic_panel'

    async def ingest(
        self,
        raw_content: dict[str, Any],
        project_id: str,
        user_id: str,
    ) -> ContentSegment:
        """将漫剧分镜推送转换为 ContentSegment。

        期望 raw_content 格式:
        {
            "sequence_number": 42,
            "title": "P3-2 对峙",
            "content": "分镜脚本描述...",
            "metadata": {
                "page": 3,
                "panel": 2,
                "characters_visual": [
                    {"name": "主角", "appearance": "黑衣长发", "expression": "愤怒"}
                ],
                "scene": "废弃工厂，夜晚",
                "camera_angle": "medium",
                "transition_type": "cut"
            }
        }
        """
        metadata = raw_content.get('metadata', {})

        segment = ContentSegment(
            project_id=project_id,
            user_id=user_id,
            content_type='comic_panel',
            sequence_number=raw_content.get('sequence_number', 0),
            title=raw_content.get('title', ''),
            content=raw_content.get('content', ''),
            metadata_json={
                'page': metadata.get('page', 0),
                'panel': metadata.get('panel', 0),
                'characters_visual': metadata.get('characters_visual', []),
                'scene': metadata.get('scene', ''),
                'camera_angle': metadata.get('camera_angle', ''),
                'transition_type': metadata.get('transition_type', ''),
                'dialogue': metadata.get('dialogue', []),
            },
        )
        return segment

    async def extract_entities(self, segment: ContentSegment) -> dict[str, Any]:
        """从漫剧分镜提取实体。"""
        meta = segment.metadata_json or {}
        characters = [
            cv.get('name', '')
            for cv in meta.get('characters_visual', [])
            if cv.get('name')
        ]
        return {
            'characters': characters,
            'characters_visual': meta.get('characters_visual', []),
            'scene': meta.get('scene', ''),
            'camera_angle': meta.get('camera_angle', ''),
            'page': meta.get('page', 0),
            'panel': meta.get('panel', 0),
        }

    def get_scan_dimensions(self) -> list[str]:
        """漫剧支持的扫描维度。"""
        return [
            'visual_consistency',
            'scene_continuity',
            'panel_transition',
            'dialogue_bubble',
        ]

    def validate_input(self, raw_content: dict[str, Any]) -> tuple[bool, str]:
        """校验漫剧输入。"""
        metadata = raw_content.get('metadata', {})
        if not raw_content.get('sequence_number'):
            return False, 'sequence_number（分镜序号）不能为空'
        if not metadata.get('page'):
            return False, 'metadata.page（页码）不能为空'
        if not metadata.get('panel'):
            return False, 'metadata.panel（分镜号）不能为空'
        return True, ''
