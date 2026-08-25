"""MCP 工具调用客户端（独立部署桩实现）。

主系统中连接用户配置的 MCP 服务器执行工具调用；
独立部署下无 MCP 基础设施，提供空降级实现：
- batch_call_tools    → 返回空列表（不阻塞 AI 主流程）
- build_tool_context  → 返回空文本
"""
import logging

logger = logging.getLogger(__name__)


class NoopMCPClient:
    """空 MCP 客户端（安全降级）。"""

    def __init__(self):
        logger.info('[MCP] 独立部署桩模式：MCP 工具调用不可用，将直接返回空结果')

    async def batch_call_tools(self, user_id='', tool_calls=None):
        return []

    def build_tool_context(self, tool_results, format='markdown'):
        return ''


mcp_client = NoopMCPClient()

__all__ = ['mcp_client', 'NoopMCPClient']
