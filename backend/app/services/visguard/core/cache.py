"""VisGuard 三级缓存管理器。

层级设计：
- L1 内存 TTL 缓存（默认 3600s）：进程内最快，OrderedDict + 过期惰性清理。
- L2 Redis（可选）：复用 app.utils.redis_client 单例；Redis 未配置或异常时
  静默降级跳过（不影响服务可用性）。
- L3 磁盘缓存：cache_dir/{namespace}/{key}.json，原子写（tmp+rename），
  超配额时按 mtime 淘汰最旧文件。

值约束：仅接受 JSON 可序列化类型（dict/list/str/num/bool/None），
避免 pickle 反序列化安全风险；非安全类型 set 时抛 ValueError。
"""

import json
import logging
import threading
import time
from collections import OrderedDict
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CacheNamespace(str, Enum):
    """缓存命名空间（按缓存类型隔离，互不污染）。"""

    PREPROCESS = 'preprocess'
    GENERATION = 'generation'
    SIMILARITY = 'similarity'


class CacheKey:
    """缓存键构造器（同一语义的键全局唯一）。"""

    _GEN_FIELDS = (
        'provider', 'model', 'prompt', 'negative_prompt', 'width', 'height',
        'steps', 'cfg', 'seed', 'control_type', 'control_weight', 'character_id',
    )

    @staticmethod
    def preprocess(image_hash: str, ptype: str, resolution: int) -> str:
        return f'pre:{image_hash}:{ptype}:{resolution}'

    @staticmethod
    def generation(params: dict) -> str:
        """生图缓存键 = 规范化参数子集的 sha256（相同参数必命中同一键）。"""
        import hashlib

        canonical = {k: params.get(k) for k in CacheKey._GEN_FIELDS}
        content = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
        return f'gen:{hashlib.sha256(content.encode()).hexdigest()[:24]}'

    @staticmethod
    def similarity(image_hash: str, top_k: int, threshold: float) -> str:
        return f'sim:{image_hash}:{top_k}:{round(float(threshold), 4)}'


class CacheManager:
    """三级缓存管理器（线程安全）。"""

    def __init__(
        self,
        cache_dir: str,
        max_size_mb: int = 1024,
        enable_redis: bool = True,
        default_ttl: int = 3600,
    ):
        self.cache_dir = Path(cache_dir)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.enable_redis = enable_redis
        self.default_ttl = default_ttl

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._memory: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits: dict[CacheNamespace, int] = {ns: 0 for ns in CacheNamespace}
        self._misses: dict[CacheNamespace, int] = {ns: 0 for ns in CacheNamespace}

    # ------------------------------------------------------------------
    # 读 / 写
    # ------------------------------------------------------------------

    def get(self, namespace: CacheNamespace, key: str, ttl: int | None = None) -> Any | None:
        """三级查找：L1(带 TTL 上浮) → L2 Redis → L3 磁盘；未命中返回 None。

        Redis 命中时回填 L1（加快后续访问）。
        """
        ttl = ttl or self.default_ttl
        full_key = f'{namespace.value}:{key}'

        # L1 内存 TTL
        with self._lock:
            if full_key in self._memory:
                value, expire = self._memory[full_key]
                if expire > time.time():
                    self._hits[namespace] += 1
                    self._memory.move_to_end(full_key)
                    return value
                del self._memory[full_key]

        # L2 Redis（可选，降级容忍）
        value = self._redis_get(full_key)
        if value is not None:
            self._hits[namespace] += 1
            with self._lock:
                self._memory[full_key] = (value, time.time() + ttl)
            return value

        # L3 磁盘
        value = self._disk_get(namespace, key)
        if value is not None:
            self._hits[namespace] += 1
            with self._lock:
                self._memory[full_key] = (value, time.time() + ttl)
            return value

        self._misses[namespace] += 1
        return None

    def set(self, namespace: CacheNamespace, key: str, value: Any, ttl: int | None = None) -> None:
        """写入三级缓存；值必须 JSON 可序列化，否则抛 ValueError。"""
        ttl = ttl or self.default_ttl
        full_key = f'{namespace.value}:{key}'

        # 值安全校验（禁止 pickle，防反序列化攻击）
        try:
            json.dumps(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f'缓存值必须 JSON 可序列化: {e}') from e

        with self._lock:
            self._memory[full_key] = (value, time.time() + ttl)
            self._memory.move_to_end(full_key)

        self._redis_set(full_key, value, ttl)
        self._disk_set(namespace, key, value)
        self._enforce_quota()

    # ------------------------------------------------------------------
    # 失效 / 统计
    # ------------------------------------------------------------------

    def invalidate_character(self, character_id: str) -> None:
        """角色更新时清除所有关联缓存。"""
        with self._lock:
            for k in [k for k in self._memory if character_id in k]:
                del self._memory[k]
        # 磁盘按 mtime 扫描匹配文件（目录量可控时够用）
        for f in self.cache_dir.rglob(f'*{character_id}*'):
            try:
                f.unlink()
            except OSError:
                pass

    def stats(self) -> dict:
        """缓存命中统计。"""
        with self._lock:
            memory_entries = len(self._memory)
        disk_entries = sum(1 for _ in self.cache_dir.rglob('*.json'))
        result: dict = {'memory_entries': memory_entries, 'disk_entries': disk_entries}
        for ns in CacheNamespace:
            h = self._hits[ns]
            m = self._misses[ns]
            result[ns.value] = {
                'hits': h,
                'misses': m,
                'hit_rate': round(h / (h + m), 4) if (h + m) > 0 else 0.0,
            }
        return result

    # ------------------------------------------------------------------
    # L2 Redis
    # ------------------------------------------------------------------

    def _redis_get(self, full_key: str) -> Any | None:
        if not self.enable_redis:
            return None
        try:
            from app.utils.redis_client import redis_client

            if redis_client is None:
                return None
            raw = redis_client.get(f'vg:{full_key}')
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:  # noqa: BLE001 - Redis 故障降级
            logger.debug('[VisGuard][Cache] Redis 读取降级: %s', e)
            return None

    def _redis_set(self, full_key: str, value: Any, ttl: int) -> None:
        if not self.enable_redis:
            return
        try:
            from app.utils.redis_client import redis_client

            if redis_client is None:
                return
            redis_client.set(f'vg:{full_key}', json.dumps(value, ensure_ascii=False), ttl=ttl)
        except Exception as e:  # noqa: BLE001
            logger.debug('[VisGuard][Cache] Redis 写入降级: %s', e)

    # ------------------------------------------------------------------
    # L3 磁盘
    # ------------------------------------------------------------------

    def _disk_path(self, namespace: CacheNamespace, key: str) -> Path:
        return self.cache_dir / namespace.value / f'{key}.json'

    def _disk_get(self, namespace: CacheNamespace, key: str) -> Any | None:
        path = self._disk_path(namespace, key)
        if not path.exists():
            return None
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:  # noqa: BLE001 - 损坏按未命中处理
            logger.debug('[VisGuard][Cache] 磁盘缓存读取失败: %s', e)
            return None

    def _disk_set(self, namespace: CacheNamespace, key: str, value: Any) -> None:
        path = self._disk_path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.json.tmp')
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(value, f, ensure_ascii=False)
            tmp.replace(path)
        except OSError as e:
            logger.warning('[VisGuard][Cache] 磁盘缓存写入失败: %s', e)

    def _enforce_quota(self) -> None:
        """超配额时按 mtime 淘汰最旧文件。"""
        total = sum(f.stat().st_size for f in self.cache_dir.rglob('*.json'))
        if total <= self.max_size_bytes:
            return
        files = sorted(self.cache_dir.rglob('*.json'), key=lambda f: f.stat().st_mtime)
        for f in files:
            if total <= self.max_size_bytes:
                break
            size = f.stat().st_size
            try:
                f.unlink()
                total -= size
            except OSError:
                continue