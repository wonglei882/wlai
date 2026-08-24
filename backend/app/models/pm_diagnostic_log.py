"""PM 诊断日志 — 持久化诊断结果，支持问题追踪"""

from sqlalchemy import Column, String, Integer, DateTime, Boolean, Index
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class PMDiagnosticLog(Base):
    """诊断日志表：存储各类型诊断结果，支持追踪是否已处理"""

    __tablename__ = 'pm_diagnostic_logs'

    __table_args__ = (
        Index('idx_diag_project', 'project_id'),
        Index('idx_diag_user', 'user_id'),
        Index('idx_diag_type', 'diag_type'),
        Index('idx_diag_resolved', 'resolved'),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), nullable=False, index=True)

    # 诊断类型
    diag_type = Column(
        String(50),
        nullable=False,
        index=True,
        comment='类型：foreshadow_overdue/consistency_issue/style_drift/chapter_quality/pov_issue/arc_incomplete/relationship_gap/other',
    )
    severity = Column(String(20), default='warning', comment='warning / critical')
    message = Column(String(500), nullable=False, comment='诊断摘要')
    suggestion = Column(String(500), comment='修复建议')

    # 上下文（便于定位问题）
    chapter_number = Column(Integer, comment='涉及章节号')
    character_id = Column(String(36), comment='涉及角色ID')

    # 追踪
    resolved = Column(Boolean, default=False, index=True)
    resolved_at = Column(DateTime, comment='处理时间')
    resolved_by = Column(String(100), comment='处理方式：auto_fix/manual')

    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f'<PMDiagnosticLog(type={self.diag_type}, severity={self.severity}, resolved={self.resolved})>'
