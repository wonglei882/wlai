"""Redis 客户端单例（可选依赖，失败自动降级为 None）。

独立部署时若未提供 Redis 服务，redis_client 为 None，
调用方（如 pm_control.py）会自动切换到文件持久化降级路径。

兼容性说明：对外暴露的 `set(name, value, ttl=...)` 中的 ttl 参数
是项目内的既有约定，内部映射为 redis-py 的 ex=。
"""
import logging

from app.config import settings

logger = logging.getLogger(__name__)

redis_client = None

try:
    import redis as _redis


    class _CompatRedis:
        """兼容 redis.Redis 的最小包装：set 支持 ttl= 别名（映射为 ex=）。"""

        def __init__(self, client):
            self._client = client

        def ping(self):
            return self._client.ping()

        def get(self, name):
            return self._client.get(name)

        def set(self, name, value, ttl=None, **kwargs):
            kwargs.pop('ex', None)
            return self._client.set(name, value, ex=ttl, **kwargs)


    _client = _redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    _client.ping()
    redis_client = _CompatRedis(_client)
    logger.info('Redis 客户端初始化成功: %s', settings.redis_url)
except Exception as e:  # pragma: no cover - 取决于部署环境
    logger.warning('Redis 客户端初始化失败，将使用文件降级: %s', e)
    redis_client = None
