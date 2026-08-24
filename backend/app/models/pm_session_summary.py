"""PM Agent 对话摘要模型 — 存储每次对话的关键决策点，用于跨次记忆。"""

from sqlalchemy import Column, String, Text, Float, DateTime, Integer, ForeignKey
from app.models.base import Base
from app.services.pm.pm_time import pm_now


class PMSessionSummary(Base):
    """PM Agent 对话摘要"""

    __tablename__ = 'pm_session_summaries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    session_id = Column(String(36), nullable=False, index=True)
    summary_type = Column(String(20), default='decision')  # decision | preference | warning
    content = Column(Text, nullable=False)  # 自然语言摘要
    importance = Column(Float, default=0.5)  # 0.0-1.0，用于排序
    created_at = Column(DateTime, default=pm_now)

    def to_dict(self):
        """ToDict

        Args:
            self:

        Returns:
            None
        """
        return {
            'id': self.id,
            'project_id': self.project_id,
            'session_id': self.session_id,
            'summary_type': self.summary_type,
            'content': self.content,
            'importance': self.importance,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
