"""OOC（角色越界）违规记录模型。

供 guardian/ooc_detector 与 proactive_reporter 使用：
- 顶层导入：`from app.models.ooc_violation import OOCViolation as OOCModel`
- 写入字段见 ooc_detector.save_violations（excerpt/reason/suggestion 已截断）
- 查询见 proactive_reporter（project_id + status='open' + severity in high/critical，按 created_at 倒序）
"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, func

from app.models.base import Base


class OOCViolation(Base):
    """OOC 违规记录（角色行为越界检测结果）。"""

    __tablename__ = 'ooc_violations'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    chapter_id = Column(String(36), nullable=False, index=True)
    character_id = Column(String(36), nullable=False, default='', index=True)
    severity = Column(String(20), nullable=False, default='low')       # critical / high / medium / low
    violation_type = Column(String(50), nullable=False, default='action_ooc')
    excerpt = Column(Text, nullable=False, default='')                 # 触发片段（300 截断）
    reason = Column(Text, nullable=False, default='')                  # 判据说明（500 截断）
    suggestion = Column(Text, nullable=False, default='')              # 修复建议（500 截断）
    status = Column(String(20), nullable=False, default='open')        # open / resolved / ignored
    created_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index('ix_ooc_violations_project_status', 'project_id', 'status'),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f'<OOCViolation project={self.project_id} chapter={self.chapter_id} {self.violation_type}>'
