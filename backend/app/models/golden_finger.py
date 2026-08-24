"""金手指数据模型"""

from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class GoldenFinger(Base):
    """金手指"""

    __tablename__ = 'golden_fingers'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True, comment='所属项目ID')
    character_id = Column(String(36), nullable=True, comment='关联角色ID')
    name = Column(String(100), nullable=False, comment='金手指名称')
    appearance = Column(Text, nullable=True, comment='表现形式')
    personality_consciousness = Column(Text, nullable=True, comment='性格/意识')
    core_functions = Column(Text, nullable=True, comment='核心功能')
    energy_consumption = Column(Text, nullable=True, comment='能量消耗')
    limitations_costs = Column(Text, nullable=True, comment='限制/代价')
    background = Column(Text, nullable=True, comment='背景故事')
    avatar_url = Column(String(500), nullable=True, comment='头像URL')
    traits = Column(Text, nullable=True, comment='特性标签')
    created_at = Column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间')
