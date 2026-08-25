"""用户 AI 服务设置查询（独立部署实现）。

主系统中按用户/用量类型返回其绑定的 AI 服务配置；
独立部署下无用户绑定关系，统一返回基于全局 settings 的默认 AIService。
"""
import logging

logger = logging.getLogger(__name__)


async def get_user_ai_service_from_db_by_usage(user_id: str, db=None, usage_type: str = 'default'):
    """按用户与用量类型获取 AI 服务实例（独立部署：返回全局默认实例）。"""
    from app.services.ai.ai_service import AIService

    return AIService()
