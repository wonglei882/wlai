"""PM Agent 自主度配置模型 — 对应 pm_autonomy_config 表。

控制 PM Agent 的决策自主程度：
- advisor:      只给建议，用户确认才执行（默认）
- advisor_plus:  常规决策自动执行，复杂/低置信度询问
- autonomous:   全自动，事后汇报
"""

from sqlalchemy import Column, String, Float, DateTime
from sqlalchemy.sql import func
from app.models.base import Base


class PMAutonomyConfig(Base):
    """PMAutonomyConfig"""

    __tablename__ = 'pm_autonomy_config'

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), nullable=False, index=True)

    # 自主度级别
    level = Column(
        String(20),
        nullable=False,
        default='advisor',
        comment='advisor | advisor_plus | autonomous',
    )

    # 置信度阈值（advisor_plus 模式使用）
    confidence_threshold = Column(
        Float,
        nullable=False,
        default=0.6,
        comment='>threshold 自动执行，<threshold 询问用户',
    )

    # 哪些决策类型可以自动执行（JSON 数组）
    auto_execute_types = Column(
        String(500),
        nullable=False,
        default='outline,suggest,foreshadow,character,world_setting',
        comment='允许自动执行的工具类型',
    )

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    @property
    def level_cn(self) -> str:
        mapping = {
            'advisor': '建议模式',
            'advisor_plus': '增强建议',
            'autonomous': '自主模式',
        }
        return mapping.get(self.level, self.level)
