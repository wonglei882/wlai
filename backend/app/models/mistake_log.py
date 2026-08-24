"""错误登记册 - 项目主管 Agent 的结构化错误记录与分类"""

from sqlalchemy import Column, String, Integer, DateTime, JSON, Text
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class MistakeLog(Base):
    """错误登记册 - 记录 AI 命令执行失败的结构化信息，用于模式分析和自优化"""

    __tablename__ = 'mistake_logs'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True, comment='项目ID')
    user_id = Column(String(100), nullable=False, index=True, comment='用户ID')

    # 关联的审计日志ID
    audit_log_id = Column(String(36), comment='关联的 CommandAuditLog ID')

    # 错误信息
    command_name = Column(String(64), nullable=False, index=True, comment='失败的命令名称')
    error_type = Column(
        String(64), default='unknown', index=True, comment='错误分类: unknown_command/execution_error/validation_error/timeout/permission'
    )
    error_message = Column(Text, comment='原始错误信息')

    # 参数快照
    params = Column(JSON, comment='命令参数 (JSON)')

    # 自优化字段
    root_cause = Column(String(500), comment='自动推断的根因')
    solution = Column(String(500), comment='建议的解决方案')
    frequency = Column(Integer, default=1, comment='同类错误累计次数')
    resolved = Column(Integer, default=0, comment='是否已修复 0/1')
    resolved_at = Column(DateTime, comment='修复时间')

    # 时间记录
    created_at = Column(DateTime, server_default=func.now(), nullable=False, comment='错误发生时间')
