"""异步任务模型 — 后台任务状态追踪。

支持长时间运行的生成任务（分镜生成/出图/视频/配音）。
"""

import uuid

from sqlalchemy import Column, String, Text, Float, DateTime
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.sql import func

from app.models.base import Base


class AsyncTask(Base):
    """异步任务 — 后台任务状态追踪。"""

    __tablename__ = 'async_tasks'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)

    task_type = Column(
        String(50), nullable=False, index=True,
        comment="任务类型: 'storyboard_gen'/'image_gen'/'video_gen'/'voice_gen'/'prompt_compile'",
    )
    status = Column(
        String(20), nullable=False, default='pending', index=True,
        comment="状态: 'pending'/'running'/'completed'/'failed'",
    )
    progress = Column(Float, default=0.0, comment='进度 0.0 ~ 1.0')
    result = Column(JSON, default=dict, comment='任务结果')
    error = Column(Text, comment='错误信息')

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
