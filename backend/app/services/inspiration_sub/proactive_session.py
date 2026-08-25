"""主动灵感会话（独立部署桩实现）。

主系统中由主进程启动时确保全局技能库就绪；
独立部署下无全局技能库依赖，提供空实现保证调用安全。
"""
import logging

logger = logging.getLogger(__name__)

_global_initialized = False


def _ensure_global_skills() -> None:
    """确保全局技能库就绪（独立部署空实现）。"""
    global _global_initialized
    if not _global_initialized:
        logger.info('[proactive_session] 全局技能库初始化（独立部署空实现）')
        _global_initialized = True
