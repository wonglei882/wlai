"""PM 用户水平画像 — 自适应输出的依据"""

from sqlalchemy import Column, String, Integer, DateTime, JSON
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class PMUserProfile(Base):
    """每个用户的 PM 使用画像，用于自适应输出级别。"""

    __tablename__ = 'pm_user_profiles'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, unique=True, index=True)

    # 水平等级
    experience_level = Column(String(20), nullable=False, default='beginner', comment='beginner / intermediate / expert')

    # 行为统计
    total_sessions = Column(Integer, nullable=False, default=0)
    total_tool_calls = Column(Integer, nullable=False, default=0)
    avg_session_chars = Column(Integer, nullable=False, default=0, comment='平均每 session 输入字数')

    # 已掌握的 skill 列表（JSON）
    skills_mastered = Column(JSON, nullable=False, default=list, comment='已熟练使用的 skill 名称列表')

    # 输出偏好
    preferred_detail_level = Column(String(10), nullable=False, default='medium', comment='high / medium / low')

    # LLM 推断的详细水平描述
    detail_prompt_hint = Column(String(200), nullable=True, comment='系统 prompt 中使用的语气提示')

    # 动态窗口（最近 N 次对话的滑动统计）
    recent_tool_diversity = Column(Integer, nullable=False, default=0, comment='最近10次对话用过的不同工具数')

    # 问题类型（改2：双维度水平检测）
    last_question_type = Column(String(20), nullable=True, comment='上次对话的问题类型: beginner/intermediate/expert')
    question_type_counts = Column(JSON, nullable=False, default=dict, comment='各问题类型计数: {"beginner":0,"intermediate":0,"expert":0}')

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
