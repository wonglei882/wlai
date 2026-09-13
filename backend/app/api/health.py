"""健康检查与运行时监控端点。

提供：
- GET /health          — 基础存活检查（liveness）
- GET /health/ready    — 就绪检查（DB + Redis 连通性）
- GET /health/metrics  — 基础指标（会话统计、引擎缓存、进程内存）
"""

import time

from fastapi import APIRouter
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/health', tags=['Health'])


@router.get('', summary='存活检查（Liveness）')
async def liveness():
    """基础存活探针 — 进程在跑即返回 200。"""
    return {
        'status': 'ok',
        'service': 'wlai-pm-backend',
        'version': '2.0.0',
        'timestamp': time.time(),
    }


@router.get('/ready', summary='就绪检查（Readiness）')
async def readiness():
    """就绪探针 — 检查 DB 与 Redis 连通性。

    各组件独立探测，某一组件失败不影响其他组件的状态上报。
    """
    components: dict[str, dict] = {}

    # DB 检查
    components['database'] = await _check_database()

    # Redis 检查
    components['redis'] = _check_redis()

    # 总体状态
    all_ok = all(c.get('status') == 'ok' for c in components.values())

    return {
        'status': 'ok' if all_ok else 'degraded',
        'components': components,
        'timestamp': time.time(),
    }


@router.get('/metrics', summary='运行时指标')
async def metrics():
    """基础运行时指标 — 供运维监控使用。"""
    import psutil
    import os

    process = psutil.Process(os.getpid())

    # 数据库会话统计
    from app.database import _session_stats
    session_stats = dict(_session_stats)

    # 数据库引擎缓存大小
    from app.database import _engine_cache
    engine_cache_size = len(_engine_cache)

    return {
        'process': {
            'memory_mb': round(process.memory_info().rss / 1024 / 1024, 1),
            'cpu_percent': process.cpu_percent(interval=0),
            'threads': process.num_threads(),
        },
        'database': {
            'engine_cache_size': engine_cache_size,
            'session_stats': session_stats,
        },
        'timestamp': time.time(),
    }


# =============================================================================
# 内部检查函数
# =============================================================================


async def _check_database() -> dict:
    """检查数据库连通性。"""
    try:
        from app.database import get_db_session_for_health

        async for session in get_db_session_for_health():
            await session.execute(text('SELECT 1'))
            return {'status': 'ok', 'latency_ms': 0}
    except Exception as e:
        logger.debug('[Health] DB 检查失败: %s', e)
        return {'status': 'error', 'detail': '数据库不可达'}


def _check_redis() -> dict:
    """检查 Redis 连通性。"""
    try:
        from app.utils.redis_client import redis_client

        if redis_client is None:
            return {'status': 'skipped', 'detail': 'Redis 未配置'}
        result = redis_client.ping()
        if result:
            return {'status': 'ok'}
        return {'status': 'error', 'detail': 'Redis PING 失败'}
    except Exception as e:
        logger.debug('[Health] Redis 检查失败: %s', e)
        return {'status': 'error', 'detail': 'Redis 不可达'}
