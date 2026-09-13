"""漫剧审核检查点模型 — 人工审核点（human-in-the-loop）。

关键节点必须让人确认：角色定稿、分镜确认、首帧确认、视频确认、成片确认。
AI 不稳定时，human-in-the-loop 比全自动更靠谱。
"""

import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.models.base import Base


class ReviewCheckpoint(Base):
    """人工审核点 — 记录审核状态与审核意见。"""

    __tablename__ = 'comic_review_checkpoints'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    user_id = Column(String(100), nullable=False, index=True)

    # 被审核对象
    target_type = Column(
        String(50), nullable=False,
        comment="被审核对象类型: 'character_card'/'storyboard'/'shot'/'episode'",
    )
    target_id = Column(
        String(36), nullable=False, index=True,
        comment='被审核对象 ID',
    )

    # 审核类型
    review_type = Column(
        String(50), nullable=False,
        comment="审核类型: 'character_design'/'storyboard_confirm'/'first_frame'/'video_confirm'/'final_cut'",
    )

    # 审核状态
    status = Column(
        String(30), nullable=False, default='pending',
        comment="审核状态: 'pending'/'approved'/'rejected'/'revision_requested'",
    )

    # 审核信息
    reviewer_notes = Column(Text, nullable=True, comment='审核意见')
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(String(100), nullable=True, comment='审核人')

    # 元数据
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )
