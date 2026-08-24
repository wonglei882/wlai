"""
PMDecisionLog — PM Agent 决策记录模型

记录每次 PM Agent 对问题的判断和修复动作，供用户可见。
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, Index
from app.models.base import Base


class PMDecisionLog(Base):
    """PM决策Log"""

    __tablename__ = 'pm_decision_log'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), index=True)
    user_id = Column(String(100), index=True)

    # 原始问题信息
    diag_type = Column(String(50))  # character_location_jump / foreshadow_stale / world_rule_drift / ...
    chapter_number = Column(Integer, nullable=True)
    severity = Column(String(20), default='warning')  # critical / warning / info
    original_message = Column(Text, nullable=True)  # 原始问题描述（diagnostic_log.message）

    # 决策信息
    decision = Column(String(20))  # auto_fix / alert / skip / pending
    decision_reason = Column(Text, nullable=True)  # 判断依据

    # 修复信息
    fix_action = Column(Text, nullable=True)  # 执行了什么修复（handler 名或描述）
    fix_result = Column(String(20), default='pending')  # pending / success / partial / failed / skipped
    fix_attempted = Column(Boolean, default=False)
    fix_details = Column(Text, nullable=True)  # 修复执行明细（JSON：改了哪些行/建了哪些记录）

    # 验证信息
    verified = Column(Boolean, default=False)
    verified_at = Column(DateTime, nullable=True)
    verify_message = Column(Text, nullable=True)  # 验证结果说明

    # 用户反馈（修复报告闭环：认可/驳回）
    user_feedback = Column(String(20), nullable=True)  # approved / rejected
    feedback_note = Column(Text, nullable=True)  # 用户备注
    feedback_at = Column(DateTime, nullable=True)

    # 质量分对比（quality_score_low 类型专用）
    original_score = Column(Integer, nullable=True)  # 修复前的分数（0-100）
    post_fix_score = Column(Integer, nullable=True)  # 修复后的分数（0-100）
    score_delta = Column(Integer, nullable=True)  # 分数差值（post - original）

    # 元信息
    scan_round = Column(String(50), nullable=True)  # 本轮巡检的 round id（用于去重）
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index('idx_pm_decision_project_created', 'project_id', 'created_at'),
        Index('idx_pm_decision_resolved', 'project_id', 'verified'),
    )

    def to_summary(self) -> dict:
        """ToSummary

        Args:
            self:

        Returns:
            dict
        """
        return {
            'id': self.id,
            'project_id': self.project_id,
            'diag_type': self.diag_type,
            'severity': self.severity,
            'chapter': self.chapter_number,
            'decision': self.decision,
            'fix_action': self.fix_action,
            'fix_result': self.fix_result,
            'verified': self.verified,
            'created_at': str(self.created_at or ''),
        }
