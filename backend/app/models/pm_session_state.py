"""PM 跨 Session 项目进度状态快照"""

from sqlalchemy import Column, String, DateTime, JSON, Float
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class PMSessionState(Base):
    """每个项目最近一次 PM 操作的状态快照，供下次 Session 恢复进度。"""

    __tablename__ = 'pm_session_state'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)

    # 上次操作摘要
    last_action = Column(String(500), nullable=True, comment='上次操作的文字描述')
    last_tool = Column(String(100), nullable=True, comment='上次调用的工具名')
    last_chapter_id = Column(String(36), nullable=True, comment='关联的章节ID')

    # 待办目标（JSON 数组）
    pending_goals = Column(JSON, nullable=False, default=list, comment='未完成的goals列表')

    # 置信度
    confidence_score = Column(Float, nullable=False, default=1.0, comment='上次操作的成功置信度 0-1')

    # 扩展数据（质量预报/自调参状态等）
    extra_data = Column(JSON, nullable=False, default=dict, comment='扩展数据：quality_forecast / self_tuning 等')

    # 时间戳
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
