"""PM 操作日志 —— 记录所有写操作，支持通用回滚"""

from sqlalchemy import Column, String, Text, DateTime, JSON, func
from app.models.base import Base
import uuid


class PMActionLog(Base):
    """PM 所有写操作的日志表，用于通用回滚（不只章节正文）"""

    __tablename__ = 'pm_action_log'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)

    # 操作类型
    tool_name = Column(String(100), nullable=False, index=True, comment='调用的工具名')
    table_name = Column(String(50), nullable=True, comment='操作的数据库表')

    # 操作目标
    target_id = Column(String(36), nullable=True, comment='操作对象的主键ID')
    target_type = Column(String(50), nullable=True, comment='目标类型：chapter/character/foreshadow...')

    # 快照（JSON，记录操作前的完整状态）
    snapshot_before = Column(JSON, nullable=True, comment='操作前的完整状态快照')
    snapshot_after = Column(JSON, nullable=True, comment='操作后的状态（用于验证）')

    # 操作参数
    params_json = Column(Text, nullable=True, comment='原始调用参数（JSON）')

    # 元数据
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = ({'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},)
