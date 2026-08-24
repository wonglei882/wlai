"""角色关系模型（PM 关系网）。

使用点（event_bus_listeners.py）：
- 创建：显式传 id/project_id/character_from_id/character_to_id/intimacy_level/status/source
- 更新：intimacy_level、updated_at 手动赋值
- 批量查询：project_id + character_from_id.in_ + character_to_id.in_
- pm_write_diagnose.py 会读取 relationship_name 统计关系分布。
"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, func

from app.models.base import Base


class CharacterRelationship(Base):
    """角色间关系（亲密度 -100 ~ 100）。"""

    __tablename__ = 'character_relationships'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    character_from_id = Column(String(36), nullable=False, index=True)
    character_to_id = Column(String(36), nullable=False, index=True)
    relationship_name = Column(String(50), default='未知关系')
    intimacy_level = Column(Integer, default=50)
    status = Column(String(20), default='active')
    source = Column(String(20), default='ai')
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_char_rels_from_to', 'project_id', 'character_from_id', 'character_to_id'),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f'<CharacterRelationship {self.character_from_id}→{self.character_to_id} {self.relationship_name}>'
