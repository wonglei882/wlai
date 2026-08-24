"""大纲数据模型"""

from typing import TYPE_CHECKING
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from app.models.base import Base
import json
import uuid

if TYPE_CHECKING:
    from app.schemas.outline_structure import OutlineStructure


class Outline(Base):
    """大纲表"""

    __tablename__ = 'outlines'

    __table_args__ = (Index('idx_outline_project', 'project_id'),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    title = Column(String(200), nullable=False, comment='大纲标题')
    content = Column(Text, comment='大纲内容')
    structure = Column(Text, comment='结构化大纲数据(JSON)，使用OutlineStructure schema')
    order_index = Column(Integer, comment='排序序号')
    created_at = Column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间')

    def get_structure(self) -> 'OutlineStructure':
        """解析structure为OutlineStructure对象"""
        from app.schemas.outline_structure import OutlineStructure

        if not self.structure:
            return OutlineStructure()
        try:
            data = json.loads(self.structure) if isinstance(self.structure, str) else self.structure
            return OutlineStructure(**data)
        except Exception:
            return OutlineStructure()

    def set_structure(self, obj: 'OutlineStructure'):
        """将OutlineStructure对象序列化到structure字段"""
        self.structure = obj.model_dump_json(ensure_ascii=False)

    def __repr__(self):
        return f'<Outline(id={self.id}, title={self.title})>'
