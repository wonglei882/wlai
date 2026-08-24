"""PM 历史行为模式库 — session 间学习"""

from sqlalchemy import Column, String, Integer, DateTime, JSON
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class PMHistoryPattern(Base):
    """记录用户历史行为模式，供 PM 预判下一步。"""

    __tablename__ = 'pm_history_patterns'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, index=True)
    project_id = Column(String(36), nullable=True, index=True)

    # 模式类型
    pattern_type = Column(String(32), nullable=False, comment='tool_sequence / goal_pattern / topic_pattern')

    # 模式数据（JSON）
    # tool_sequence: {"sequence": ["tool_a", "tool_b"]}
    # goal_pattern: {"goals": ["修复角色", "更新正文"]}
    # topic_pattern: {"topics": {"角色状态": 5, "伏笔": 3}}
    pattern_data = Column(JSON, nullable=False, default=dict)

    # 出现次数
    frequency = Column(Integer, nullable=False, default=1)

    # 时间戳
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
