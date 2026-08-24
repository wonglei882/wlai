"""叙事结构节点模型。

当前使用点（pm_write_diagnose.py）：
- 按 POV 角色统计章节数：select(StructureNode.pov_character_id, func.count(StructureNode.id)) group by
- 节点总数：select(func.count(StructureNode.id))
- 均为 project_id 维度只读查询，无创建点；字段按结构探测用途补全。
"""
import uuid

from sqlalchemy import Column, DateTime, Integer, String, func

from app.models.base import Base


class StructureNode(Base):
    """叙事结构节点（POV 分布 / 节奏结构探测结果）。"""

    __tablename__ = 'narrative_structure_nodes'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), index=True, nullable=False)
    chapter_number = Column(Integer, nullable=False, default=0)
    chapter_id = Column(String(36), default='')
    node_type = Column(String(30), default='pov')          # pov / plot / filler / transition ...
    label = Column(String(100), default='')
    pov_character_id = Column(String(36), nullable=True, default=None)
    description = Column(String(500), default='')
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:  # pragma: no cover
        return f'<StructureNode project={self.project_id} ch={self.chapter_number} pov={self.pov_character_id}>'
