"""章节分析任务模型（独立部署补齐）。

主系统中由后台任务执行章节的 AI 分析，该模型记录任务进度与结果；
独立部署下用于串联事件总线中的异步分析链路。
"""
import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.models.base import Base


class AnalysisTask(Base):
    __tablename__ = 'analysis_tasks'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    chapter_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), nullable=False, default='', index=True)

    # pending / running / success / failed
    status = Column(String(20), nullable=False, default='pending', index=True)
    progress = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=False, default='')

    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
