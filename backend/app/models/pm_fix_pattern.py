"""
PMFixPattern — 修复模式库（L4 经验进化）

沉淀「验证通过的修复方案」，供后续同类问题复用：
- 沉淀：auto_fix 验证通过时写入/强化
- 复用：决策评分时提升置信度（成功先例越多，越敢自动修复）
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.models.base import Base


class PMFixPattern(Base):
    """修复模式：同一问题类型验证通过的修复方案。"""

    __tablename__ = 'pm_fix_patterns'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    issue_type = Column(String(64), index=True, nullable=False)  # diag_type（含 pm_agent_ 前缀）
    pattern_text = Column(Text, nullable=True)  # 验证通过的修复方案文本
    source_decision_id = Column(String(36), nullable=True)  # 首次沉淀来源的 PMDecisionLog.id
    success_count = Column(Integer, nullable=False, default=1)  # 验证通过次数
    use_count = Column(Integer, nullable=False, default=0)  # 被复用次数
    last_used_at = Column(DateTime, nullable=True)  # 最近复用时间
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    __table_args__ = (
        Index('idx_fix_pattern_type_created', 'issue_type', 'created_at'),
    )

    def to_summary(self) -> dict:
        """修复模式摘要。"""
        return {
            'id': self.id,
            'issue_type': self.issue_type,
            'success_count': self.success_count,
            'use_count': self.use_count,
            'created_at': str(self.created_at or ''),
        }
