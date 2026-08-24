"""PM Leader Lock 模型 — 多实例部署的巡检循环互斥锁。

部署事实：当前单容器 uvicorn 单进程，此锁平时是冗余保险；
未来多实例横向扩容时，防止多个 pm_agent_loop 同时扫描造成重复告警/重复修复。

锁语义为 DB 租约锁：
- lock_name 是主键，保证全局只有一行锁记录；
- expires_at 之前的租约期内其他持有者无法抢占；
- 过期后任意实例可通过 UPDATE 接管。
"""

from sqlalchemy import Column, DateTime, String

from app.models.base import Base


class PMLeaderLock(Base):
    """PMLeaderLock"""

    __tablename__ = 'pm_leader_lock'

    # 锁名（当前仅 'pm_agent_loop'），主键保证全局唯一行
    lock_name = Column(String(50), primary_key=True, default='pm_agent_loop')

    # 持有者标识（进程唯一 ID，hostname:pid）
    holder_id = Column(String(64), nullable=False)

    # 租约到期时间：超过此时间其他实例可接管
    expires_at = Column(DateTime, nullable=False)

    updated_at = Column(DateTime, nullable=False)
