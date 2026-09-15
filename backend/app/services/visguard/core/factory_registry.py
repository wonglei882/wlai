"""能力工厂注册表 — 原子构建 + 热重载（P0-2）。

设计：
- 服务初始化时把各能力工厂注册进 registry（如 'generate' -> create_generator）；
- get() 返回当前实例（未注册 / 构建失败返回 None，不抛错）；
- reload() 重建实例：先构建新实例，成功后才原子替换（构建失败保留旧实例，回滚）；
- generation 计数随成功重建递增（供观测/日志）；
- 线程安全：构建与替换持同一把锁，避免并发 reload 撕裂状态。

与文档差异（内嵌架构落地）:
- 不在独立 service 进程内热更新（update_from_registry 语义简化为 reload + 重新读取 settings），
- reload 后由调用方决定是否重建依赖该能力的上游（如任务 runner）。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class FactoryRegistry:
    """按名字注册工厂函数，提供惰性实例 + 原子热重载。"""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], T]] = {}
        self._instances: dict[str, T | None] = {}
        self._generations: dict[str, int] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 注册 / 查询
    # ------------------------------------------------------------------

    def register(self, name: str, factory: Callable[[], T]) -> None:
        """注册工厂函数（同名覆盖；不立即构建）。"""
        with self._lock:
            self._factories[name] = factory
            self._instances[name] = None
            self._generations[name] = 0
        logger.info('[VisGuard] 注册能力工厂: %s', name)

    def get(self, name: str) -> T | None:
        """取当前实例（懒构建；未注册或构建失败返回 None）。"""
        with self._lock:
            if name not in self._factories:
                return None
            if self._instances[name] is None:
                self._instances[name] = self._build_unsafe(name)
            return self._instances[name]

    def registered(self) -> list[str]:
        """已注册的工厂名。"""
        with self._lock:
            return sorted(self._factories)

    def generation(self, name: str) -> int:
        """指定工厂的成功重建代次（0 = 尚未成功构建）。"""
        with self._lock:
            return self._generations.get(name, 0)

    # ------------------------------------------------------------------
    # 热重载
    # ------------------------------------------------------------------

    def reload(self, name: str) -> bool:
        """原子重建实例：先构建后替换，失败保留旧实例。

        Returns:
            True 重建成功；False 未注册 / 构建异常（回滚）。
        """
        with self._lock:
            if name not in self._factories:
                return False
            new_instance = self._build_unsafe(name)
            if new_instance is None:
                return False
            self._instances[name] = new_instance
            self._generations[name] += 1
            logger.info('[VisGuard] 能力工厂已重建: %s (代次 %d)', name, self._generations[name])
            return True

    def reload_all(self) -> dict[str, bool]:
        """重建全部已注册工厂，返回 {name: ok}。"""
        results: dict[str, bool] = {}
        with self._lock:
            for name in list(self._factories):
                results[name] = self.reload(name)
        return results

    def drop(self, name: str) -> None:
        """移除工厂与实例（测试 / 运维用）。"""
        with self._lock:
            self._factories.pop(name, None)
            self._instances.pop(name, None)
            self._generations.pop(name, None)

    # ------------------------------------------------------------------

    def _build_unsafe(self, name: str) -> T | None:
        """调用工厂构建实例（必须在持锁状态下调用）；异常已捕获返回 None。"""
        factory = self._factories[name]
        try:
            return factory()
        except Exception as e:  # noqa: BLE001 - 工厂失败不 cascade，get 返回 None
            logger.error('[VisGuard] 能力工厂构建失败: %s (%s)', name, e)
            return None