"""
PM 自进化模型 — 阈值进化 / 排除规则 / 进化事件

三层自进化闭环的持久化层：
1. PMEvolutionState  — 每 (project_id, dimension) 的进化状态（信号聚合 + 运行时阈值）
2. PMExclusionRule   — 用户驳回反馈学习的噪声排除规则
3. PMEvolutionEvent  — 进化动作事件日志（参数变更/规则学习/节流/回滚）
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Float, Integer, Boolean, DateTime, Index
from app.models.base import Base


class PMEvolutionState(Base):
    """PM自进化状态"""

    __tablename__ = 'pm_evolution_state'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), index=True)
    dimension = Column(String(50))  # character_consistency / foreshadow_age / ...

    # 信号聚合（近 window_hours 小时窗口）
    signals_aggregated = Column(Integer, default=0)  # 聚合轮数
    total_decisions = Column(Integer, default=0)  # 决策总数
    hit_count = Column(Integer, default=0)  # 成功命中（fix_result=success / verified）
    fp_count = Column(Integer, default=0)  # 误报（user_feedback=rejected）
    fix_rate = Column(Float, default=0.5)  # 修复成功率（后验期望）
    fp_rate = Column(Float, default=0.0)  # 误报率

    # 运行时阈值（E2 覆盖层数据源）
    threshold_key = Column(String(50), nullable=True)  # 当前进化参数名
    threshold_value = Column(Float, nullable=True)  # 运行时值
    threshold_original = Column(Float, nullable=True)  # 配置默认值
    threshold_min = Column(Float, nullable=True)
    threshold_max = Column(Float, nullable=True)
    confidence = Column(Float, default=0.5)  # 当前设置可信度

    # 变更基线（回滚评估：变更后累计 ROLLBACK_EVAL_SAMPLES 个新决策后对比）
    baseline_total_decisions = Column(Integer, nullable=True)  # 变更时的决策总数
    baseline_fp_rate = Column(Float, nullable=True)  # 变更时误报率
    baseline_fix_rate = Column(Float, nullable=True)  # 变更时修复成功率

    # 维度节流
    status = Column(String(20), default='stable')  # stable / evolving / throttled / disabled
    throttle_until = Column(DateTime, nullable=True)  # 节流到期时间
    consecutive_clean_rounds = Column(Integer, default=0)  # 连续无 issue 轮数

    last_evolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index('idx_evolution_project_dimension', 'project_id', 'dimension'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'dimension': self.dimension,
            'signals_aggregated': self.signals_aggregated,
            'total_decisions': self.total_decisions,
            'hit_count': self.hit_count,
            'fp_count': self.fp_count,
            'fix_rate': round(self.fix_rate or 0, 3),
            'fp_rate': round(self.fp_rate or 0, 3),
            'threshold_key': self.threshold_key,
            'threshold_value': self.threshold_value,
            'threshold_original': self.threshold_original,
            'threshold_min': self.threshold_min,
            'threshold_max': self.threshold_max,
            'confidence': round(self.confidence or 0, 3),
            'baseline_total_decisions': self.baseline_total_decisions,
            'baseline_fp_rate': self.baseline_fp_rate,
            'baseline_fix_rate': self.baseline_fix_rate,
            'status': self.status,
            'throttle_until': str(self.throttle_until) if self.throttle_until else None,
            'consecutive_clean_rounds': self.consecutive_clean_rounds,
            'last_evolved_at': str(self.last_evolved_at) if self.last_evolved_at else None,
            'updated_at': str(self.updated_at) if self.updated_at else None,
        }


class PMExclusionRule(Base):
    """PM排除规则 — 从用户驳回反馈学习的噪声过滤规则"""

    __tablename__ = 'pm_exclusion_rule'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), index=True)
    dimension = Column(String(50), index=True)  # 所属扫描维度
    rule_type = Column(String(30))  # character / foreshadow / chapter / dimension
    rule_key = Column(String(200))  # 匹配键（角色名/伏笔标题/章号/*）
    reason = Column(Text, nullable=True)  # 学习来源说明（用户备注）
    source = Column(String(30), default='user_rejection')  # user_rejection / auto_noise
    hits = Column(Integer, default=0)  # 命中次数（用于评估规则有效性）
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index('idx_exclusion_scope', 'project_id', 'dimension'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'dimension': self.dimension,
            'rule_type': self.rule_type,
            'rule_key': self.rule_key,
            'reason': self.reason,
            'source': self.source,
            'hits': self.hits,
            'enabled': self.enabled,
            'created_at': str(self.created_at) if self.created_at else None,
        }


class PMEvolutionEvent(Base):
    """PM进化事件日志"""

    __tablename__ = 'pm_evolution_event'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), index=True)
    dimension = Column(String(50), index=True)
    event_type = Column(String(30))  # param_change / rule_learned / throttle_on / throttle_off / rollback / round
    detail = Column(Text, nullable=True)  # JSON 明细
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index('idx_evolution_event_scope', 'project_id', 'created_at'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'dimension': self.dimension,
            'event_type': self.event_type,
            'detail': self.detail,
            'created_at': str(self.created_at) if self.created_at else None,
        }
