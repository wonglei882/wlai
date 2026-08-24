"""PM Token 使用记录模型

记录每次巡检/修复的 token 消耗
"""

from sqlalchemy import Column, String, Integer, DateTime, Text, Index
from app.models.base import Base
from app.services.pm.pm_time import pm_now


class PMTokenUsage(Base):
    """PM Token 使用记录"""

    __tablename__ = 'pm_token_usage'

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), nullable=False, index=True)

    # Token 消耗
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    # 功能分类
    feature = Column(String(50), nullable=False)  # inspection/repair/llm_suggestion
    action = Column(String(100))  # world_drift/foreshadow_stale/...

    # 模型信息
    model = Column(String(100))
    provider = Column(String(50))

    # 成本（美元）
    cost_usd = Column(Integer, default=0)  # 单位：微美元（1e-6 USD）

    # 时间
    created_at = Column(DateTime, default=pm_now, index=True)

    # 详情
    details = Column(Text)  # JSON 格式的详细信息

    __table_args__ = (
        Index('idx_pm_token_project_created', 'project_id', 'created_at'),
        Index('idx_pm_token_user_created', 'user_id', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'user_id': self.user_id,
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'total_tokens': self.total_tokens,
            'feature': self.feature,
            'action': self.action,
            'model': self.model,
            'provider': self.provider,
            'cost_usd': self.cost_usd,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'details': self.details,
        }
