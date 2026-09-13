"""通用内容片段模型 — 替代 Chapter 成为核心存储单元。

支持多模态内容类型：
- novel_chapter: 网文章节
- comic_panel: 漫剧分镜
- audio_segment: 有声书片段
- custom: 用户自定义类型

通过 content_type 字段区分领域，metadata_json 承载领域特定元数据。
"""

import uuid

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.sql import func

from app.models.base import Base


class ContentSegment(Base):
    """通用内容片段 — 统一存储各类型 AI 生成内容。"""

    __tablename__ = 'content_segments'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36),
        ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
        comment='所属项目 ID',
    )
    user_id = Column(
        String(100),
        nullable=False,
        index=True,
        comment='用户 ID',
    )

    # 内容类型标识
    content_type = Column(
        String(50),
        nullable=False,
        index=True,
        comment="内容类型: 'novel_chapter' | 'comic_panel' | 'audio_segment' | 'custom'",
    )

    # 序列信息
    sequence_number = Column(
        Integer,
        nullable=False,
        comment='序列号（章节号/分镜号/片段序号）',
    )
    title = Column(String(500), comment='标题（章节名/分镜描述）')
    content = Column(Text, comment='正文/脚本/描述文本')

    # 领域特定元数据（JSON）
    # 小说: {"characters": [...], "location": "...", "world_rules_hash": "..."}
    # 漫剧: {"page": 3, "panel": 2, "characters_visual": [...], "scene": "..."}
    metadata_json = Column(JSON, default=dict, comment='领域特定元数据')

    # 层级关系（章节 -> 分镜）
    parent_id = Column(
        String(36),
        ForeignKey('content_segments.id', ondelete='SET NULL'),
        nullable=True,
        comment='父级片段 ID（如分镜所属章节）',
    )

    # 审计字段
    created_at = Column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间')

    def __repr__(self):
        return f'<ContentSegment(id={self.id}, type={self.content_type}, seq={self.sequence_number})>'
