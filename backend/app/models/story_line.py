"""故事线数据模型"""

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class StoryLine(Base):
    """故事线"""

    __tablename__ = 'story_lines'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String(200), nullable=False, comment='故事线名称')
    line_type = Column(String(50), nullable=False, default='sub', comment='线类型: main/sub/hidden/romance')
    status = Column(String(20), nullable=False, default='active', comment='状态: active/dormant/completed/abandoned')
    color = Column(String(20), nullable=True, comment='显示颜色')
    description = Column(Text, nullable=True, comment='描述')
    sort_order = Column(Integer, default=0, comment='排序序号（画布Y轴顺序）')
    first_chapter = Column(Integer, nullable=True, comment='首次出现章节')
    latest_chapter = Column(Integer, nullable=True, comment='最近出现章节')
    event_count = Column(Integer, default=0, comment='事件数')
    extra_data = Column(JSON, nullable=True, comment='额外数据')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment='更新时间')
