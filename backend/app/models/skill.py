"""技能模型 —— 对应 skills 表"""

from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Float, Integer
from sqlalchemy.sql import func
from app.models.base import Base


class Skill(Base):
    """Skill"""

    __tablename__ = 'skills'

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'))
    user_id = Column(String(36), nullable=False)
    skill_name = Column(String(255), nullable=False)
    trigger = Column(Text, nullable=False)
    steps = Column(Text, nullable=False)
    description = Column(Text)
    enabled = Column(Boolean, default=True)
    # C方案: Skill 质量评审
    skill_type = Column(String(20), default='draft')  # draft/verified/rejected
    review_score = Column(Float, nullable=True)  # 评审分数 0.0-10.0
    review_at = Column(DateTime, nullable=True)  # 最后评审时间
    hit_count = Column(Integer, default=0)  # 被 find_matching_skill 命中次数
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
