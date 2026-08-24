"""PM-Agent 目标稳定性监控模型"""

from sqlalchemy import Column, String, Float, TIMESTAMP, JSON, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.models.base import Base


def _json_column(nullable: bool):
    """跨方言 JSON 列：生产用 PostgreSQL JSONB，测试 SQLite 自动降级为 JSON。

    解决：原直接用 JSONB 导致 SQLite 测试报
    `SQLiteTypeCompiler can't render element of type JSONB`。
    """
    return Column(JSONB().with_variant(JSON(), 'sqlite'), nullable=nullable)


class GoalStabilityLog(Base):
    """PM-Agent 目标稳定性监控：记录修复目标向量，检测偏离"""

    __tablename__ = 'goal_stability_log'

    # 原 Float 在 SQLite 下不会自动递增；改 Integer + autoincrement 兼容两种方言
    # （PostgreSQL 仍按 SERIAL 语义生成）
    id = Column(Integer, primary_key=True, autoincrement=True)
    goal_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), nullable=False, index=True)
    scan_round = Column(String(36), nullable=True)

    # 原始目标向量
    original_goal = _json_column(nullable=False)
    # {issue_type, affected_entities, repair_intent, chapter_range}

    # 修复动作
    fix_action = _json_column(nullable=True)
    # {fix_type, modified_entities, intent}

    # 偏离检测结果
    drift_score = Column(Float, nullable=True)
    drift_type = Column(String(50), nullable=True)
    # drift_type: none / entity_mismatch / intent_mismatch

    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<GoalStabilityLog(goal_id={self.goal_id}, drift={self.drift_score})>'
