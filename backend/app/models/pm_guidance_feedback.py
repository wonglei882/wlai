"""
PMGuidanceFeedback — 引导采纳反馈（L4 经验进化）

记录「苏格拉底引导」是否被采纳、问题是否因此解决，
为 V2 引导链权重调参提供信号。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String

from app.models.base import Base


class PMGuidanceFeedback(Base):
    """一次引导的采纳/解决信号。"""

    __tablename__ = 'pm_guidance_feedback'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    decision_log_id = Column(String(36), index=True, nullable=False)  # 关联引导决策日志
    project_id = Column(String(64), nullable=False, default='')
    user_id = Column(String(100), nullable=False, default='')
    issue_type = Column(String(64), nullable=False, default='')
    adopted = Column(Boolean, nullable=False, default=False)  # 用户是否采纳引导
    solved = Column(Boolean, nullable=False, default=False)  # 问题是否因此解决
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    __table_args__ = (
        Index('idx_guidance_fb_type_created', 'issue_type', 'created_at'),
    )

    def to_summary(self) -> dict:
        """反馈摘要。"""
        return {
            'id': self.id,
            'decision_log_id': self.decision_log_id,
            'issue_type': self.issue_type,
            'adopted': self.adopted,
            'solved': self.solved,
            'created_at': str(self.created_at or ''),
        }
