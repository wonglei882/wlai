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
        summary = {
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
        # Phase 4.2 审核面板：补齐字段（向后兼容，仅追加）
        summary['original_message'] = (self.original_message or '')[:200]
        summary['decision_reason'] = self.decision_reason or ''
        summary['verify_message'] = self.verify_message or ''
        summary['fix_attempted'] = self.fix_attempted
        summary['user_feedback'] = self.user_feedback
        summary['feedback_note'] = self.feedback_note or ''
        # 监督层审核摘要：从 fix_details 解析 audit_report（score/passed/红线命中）
        # 缺失/解析失败 → 返回 None，由前端决定是否展示审核面板入口
        summary['audit'] = self._extract_audit_summary()
        return summary

    def _extract_audit_summary(self) -> dict | None:
        """从 fix_details JSON 中提取监督层审核摘要（尽力而为，不抛异常）。

        返回:
            {score, passed, has_red_line, issue_count} 或 None（无审核数据）
        """
        if not self.fix_details:
            return None
        try:
            import json as _json

            parsed = _json.loads(self.fix_details)
            audit = parsed.get('audit_report')
            if not isinstance(audit, dict) or not audit.get('score'):
                return None
            issues = audit.get('issues') or []
            return {
                'score': audit.get('score'),
                'summary': audit.get('summary', ''),
                'passed': bool(audit.get('passed', False)),
                'has_red_line': any(bool(i.get('red_line_id')) for i in issues if isinstance(i, dict)),
                'issue_count': len(issues),
            }
        except Exception:
            return None
