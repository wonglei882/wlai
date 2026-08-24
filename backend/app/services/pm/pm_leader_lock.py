"""PM Leader Lock — 多实例部署的巡检循环互斥锁（DB 租约锁）。

部署事实：当前单容器 uvicorn 单进程，此锁平时是冗余保险；
未来多实例横向扩容时，防止多个 pm_agent_loop 同时扫描造成重复告警/重复修复。

可移植两步锁（不依赖方言特性，SQLite/PostgreSQL 均适用）：
1. UPDATE ... WHERE lock_name=:name AND (expires_at < :now OR holder_id=:me)
   → rowcount > 0 即获取成功（含过期接管与自身续约）
2. rowcount == 0 时尝试 INSERT；主键冲突说明他人持锁未过期 → 失败

时间边界统一用 Python 端 datetime.now() 计算，避免各数据库 now() 方言差异。
"""

import logging
import os
import socket
from datetime import datetime, timedelta

from sqlalchemy import delete, insert, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pm_leader_lock import PMLeaderLock

logger = logging.getLogger(__name__)

LOCK_NAME_PM_AGENT_LOOP = 'pm_agent_loop'
DEFAULT_TTL_SECONDS = 3600


def get_holder_id() -> str:
    """进程唯一标识：hostname:pid。"""
    return f'{socket.gethostname()}:{os.getpid()}'


async def try_acquire_leadership(
    db: AsyncSession,
    holder_id: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> bool:
    """尝试获取 leadership：成功返回 True；他人持未过期锁返回 False。

    同一持有者重复调用等价于续约（UPDATE 命中自身行）。
    """
    now = datetime.now()
    stmt = (
        update(PMLeaderLock)
        .where(
            PMLeaderLock.lock_name == LOCK_NAME_PM_AGENT_LOOP,
            (PMLeaderLock.expires_at < now) | (PMLeaderLock.holder_id == holder_id),
        )
        .values(
            holder_id=holder_id,
            expires_at=now + timedelta(seconds=ttl_seconds),
            updated_at=now,
        )
    )
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount > 0:
        return True

    # 无行可更新：要么行不存在（首次获取），要么他人持未过期锁 → 尝试 INSERT 区分
    try:
        await db.execute(
            insert(PMLeaderLock).values(
                lock_name=LOCK_NAME_PM_AGENT_LOOP,
                holder_id=holder_id,
                expires_at=now + timedelta(seconds=ttl_seconds),
                updated_at=now,
            )
        )
        await db.commit()
        return True
    except IntegrityError:
        await db.rollback()
        return False


async def renew_leadership(
    db: AsyncSession,
    holder_id: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> bool:
    """续约：仅持有者本人且租约未过期时有效，返回是否成功。"""
    now = datetime.now()
    stmt = (
        update(PMLeaderLock)
        .where(
            PMLeaderLock.lock_name == LOCK_NAME_PM_AGENT_LOOP,
            PMLeaderLock.holder_id == holder_id,
            PMLeaderLock.expires_at >= now,
        )
        .values(
            expires_at=now + timedelta(seconds=ttl_seconds),
            updated_at=now,
        )
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def release_leadership(db: AsyncSession, holder_id: str) -> None:
    """释放锁：仅删除自己持有的行（非持有者调用为 no-op）。"""
    await db.execute(
        delete(PMLeaderLock).where(
            PMLeaderLock.lock_name == LOCK_NAME_PM_AGENT_LOOP,
            PMLeaderLock.holder_id == holder_id,
        )
    )
    await db.commit()
