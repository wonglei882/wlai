"""PM 目标树 — 主目标→子目标树形结构"""

from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class PMGoalTree(Base):
    """PM 目标树，支持主目标→子目标树形结构。"""

    __tablename__ = 'pm_goal_tree'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    goal_id = Column(String(36), nullable=False, unique=True, index=True)
    parent_id = Column(String(36), nullable=True, index=True, comment='null=根目标')
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)

    # 目标内容
    goal_text = Column(String(500), nullable=False)
    status = Column(String(20), nullable=False, default='pending', comment='pending / in_progress / done / abandoned')
    priority = Column(Integer, nullable=False, default=3, comment='1-5，5最高')

    # 元数据
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
