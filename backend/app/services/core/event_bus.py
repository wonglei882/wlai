"""轻量级同步事件总线——PM 主动能力的触发层。

设计原则：
- 同步发射：emit 立即遍历所有 listener，不等异步完成
- async listener：用 asyncio.create_task，不阻塞主流程
- listener 异常：捕获后记录日志，不传播，不阻断主流程
- handler_id 去重：同 id 只注册一次，支持按 id 注销

使用方式：
    from app.services.core.event_bus import event_bus, EVENT_CHAPTER_CREATED
    event_bus.emit(EVENT_CHAPTER_CREATED, db=db, chapter_id="xxx", project_id="yyy")
"""

from collections import defaultdict
import asyncio
import logging
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

# ============================================================================
# 事件名常量
# ============================================================================
EVENT_CHAPTER_CREATED = 'chapter.created'
EVENT_CHAPTER_UPDATED = 'chapter.updated'
EVENT_CHAPTER_DELETED = 'chapter.deleted'
EVENT_CHAPTER_GENERATING = 'chapter.generating'  # 生成开始前
EVENT_CHAPTER_GENERATED = 'chapter.generated'  # 生成完成后
EVENT_CHARACTER_UPDATED = 'character.updated'
EVENT_FORESHAOW_CREATED = 'foreshadow.created'
EVENT_FORESHAOW_UPDATED = 'foreshadow.updated'
EVENT_PM_TOOL_EXECUTED = 'pm_tool.executed'
EVENT_PM_TOOL_FAILED = 'pm_tool.failed'


class EventBus:
    """事件总线单例。"""

    def __init__(self):
        # {(event_name): [(handler, handler_id), ...]}
        self._listeners: dict[str, list[tuple[Callable, Any]]] = defaultdict(list)
        self._registered_ids: set[Any] = set()  # 用于去重

    # --------------------------------------------------------------------------
    # 注册 / 注销
    # --------------------------------------------------------------------------

    def register(self, event_name: str, handler: Callable, handler_id: Any = None) -> None:
        """注册监听器。handler_id 用于去重和注销。"""
        hid = handler_id if handler_id is not None else id(handler)
        if hid in self._registered_ids:
            return  # 已注册，跳过
        self._listeners[event_name].append((handler, hid))
        self._registered_ids.add(hid)

    def unregister(self, event_name: str, handler_id: Any) -> None:
        """注销指定 handler_id 的监听器。"""
        self._listeners[event_name] = [(h, hid) for h, hid in self._listeners[event_name] if hid != handler_id]
        self._registered_ids.discard(handler_id)

    # --------------------------------------------------------------------------
    # 发射
    # --------------------------------------------------------------------------

    def emit(self, event_name: str, **kwargs) -> None:
        """同步发射事件。
        - sync handler：直接调用
        - async handler：用 create_task 异步执行，不等待
        - 异常：捕获并记录，不传播
        """
        logger.debug('[EventBus] emit: %s', event_name)
        for handler, hid in self._listeners[event_name]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    # 异步 listener 不阻塞主流程
                    asyncio.create_task(self._safe_async(handler, event_name, hid, kwargs))
                else:
                    self._safe_sync(handler, event_name, hid, kwargs)
            except RuntimeError as e:
                # event loop 未运行（启动阶段）：降级为同步调用
                if 'no running event loop' in str(e):
                    try:
                        handler(**kwargs)
                    except Exception:
                        logger.warning('[EventBus] sync fallback failed: %s.%s', event_name, hid)
                else:
                    logger.warning('[EventBus] RuntimeError: %s', e)
            except Exception as e:
                logger.warning('[EventBus] emit exception: %s.%s: %s', event_name, hid, e)

    # --------------------------------------------------------------------------
    # 内部辅助
    # --------------------------------------------------------------------------

    async def _safe_async(self, handler: Callable, event_name: str, handler_id: Any, kwargs: dict) -> None:
        """异步执行 handler，异常不传播。"""
        logger.debug('[EventBus] _safe_async START: %s.%s', event_name, handler_id)
        try:
            await handler(**kwargs)
            logger.debug('[EventBus] _safe_async DONE: %s.%s', event_name, handler_id)
        except Exception as e:
            logger.warning('[EventBus] async listener failed: %s.%s: %s', event_name, handler_id, e)

    @staticmethod
    def _safe_sync(handler: Callable, event_name: str, handler_id: Any, kwargs: dict) -> None:
        """同步执行 handler，异常不传播。"""
        try:
            handler(**kwargs)
        except Exception as e:
            logger.warning('[EventBus] sync listener failed: %s.%s: %s', event_name, handler_id, e)


# ============================================================================
# 全局单例
# ============================================================================
event_bus = EventBus()
