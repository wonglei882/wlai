"""项目管理服务（独立部署补齐）。

提供 CommandRegistry —— 复用 agent/core 的 ToolRegistry，
供 pm.py 的澄清执行接口与 CommandExecutor 配对使用。
"""
from app.agent.core.command_registry import ToolRegistry as CommandRegistry

__all__ = ['CommandRegistry']
