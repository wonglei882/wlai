"""PM 写操作基座 — 共享 imports + 响应构造器。

由 pm_write_operations.py 拆分而来。
各子模块统一从此导入共享依赖，避免重复定义。
"""

from app.logger import get_logger
from app.services.json_helper import safe_int, safe_json_loads  # noqa: F401 re-export for pm_write modules

__all__ = ['safe_int', 'safe_json_loads']

logger = get_logger(__name__)


def _make_response(success: bool, message: str, data: dict | None = None) -> dict:
    """统一响应构造器。所有 PM 写操作工具的返回值格式。"""
    return {'success': success, 'message': message, 'data': data or {}}
