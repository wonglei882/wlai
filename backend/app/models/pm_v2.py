"""项目主管强化 - V2 数据模型"""

from sqlalchemy import Column, String, Integer, DateTime, JSON, Text, Float
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class ExperienceCard(Base):
    """经验卡片 — 从高分案例中提炼的策略模式"""

    __tablename__ = 'pm_experience_cards'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    task_type = Column(String(50), nullable=False, comment='任务类型: fusion/smoothing/review')
    pattern = Column(Text, comment='模式描述（提炼的经验）')
    success_conditions = Column(Text, comment='成功条件')
    context_patterns = Column(JSON, comment='适用场景特征')
    usage_count = Column(Integer, default=0, comment='使用次数')
    success_rate = Column(Float, default=1.0, comment='成功率')
    source_scores = Column(JSON, comment='来源案例的评分详情')
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())


class FailurePattern(Base):
    """失败模式 — 从低分案例中总结的常见错误"""

    __tablename__ = 'pm_failure_patterns'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    pattern_type = Column(String(50), nullable=False, comment='模式类型: ooc/inconsistency/pace/hook')
    error_description = Column(Text, comment='错误描述')
    root_cause = Column(Text, comment='根因分析')
    recovery_suggestion = Column(Text, comment='恢复/修复建议')
    occurrence_count = Column(Integer, default=1, comment='出现次数')
    last_occurred_at = Column(DateTime, server_default=func.now())
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class UserPreference(Base):
    """用户偏好 — 学习用户的写作风格偏好"""

    __tablename__ = 'pm_user_preferences'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    preference_type = Column(String(50), nullable=False, comment='偏好类型: pacing/dialogue/description')
    value = Column(JSON, comment='偏好值')
    confidence = Column(Float, default=0.5, comment='置信度 0-1')
    source = Column(String(20), default='feedback', comment='来源: feedback/edit/review')
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())
