"""工具注册表 — 所有 TOOL 的单一入口"""

from dataclasses import dataclass, field
from collections.abc import Callable
from enum import Enum


class RiskLevel(Enum):
    """RiskLevel"""

    LOW = 'low'  # 只读操作
    MEDIUM = 'medium'  # 写入操作
    HIGH = 'high'  # 删除/危险操作


@dataclass
class ToolDefinition:
    """工具Definition"""

    name: str
    description: str
    params_schema: dict  # {param_name: description}
    required_params: list[str]
    handler: Callable
    param_types: dict = field(default_factory=dict)  # {param_name: type_hint} e.g. {"project_id": "str", "chapter_number": "int"}
    risk_level: RiskLevel = RiskLevel.MEDIUM
    pre_validators: list[Callable] = field(default_factory=list)
    post_validators: list[Callable] = field(default_factory=list)
    requires_read_first: bool = False
    # 写操作目标：(表名, id参数名, 目标类型标签) —— 用于执行前快照记录，支持回滚
    write_target: tuple | None = None


class ToolRegistry:
    """工具注册表 — 单一入口，所有 TOOL 必须在此注册"""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        key = tool.name.lower()
        if key in self._tools:
            raise ValueError(f'工具重复注册: {tool.name}')
        self._tools[key] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name.lower())

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_read_before_tools(self) -> list[str]:
        return [t.name for t in self._tools.values() if t.requires_read_first]

    def generate_prompt_docs(self) -> str:
        """生成给 AI 看的工具文档"""
        lines = ['## 可用工具', '']
        for tool in sorted(self._tools.values(), key=lambda t: t.name):
            params = ', '.join(f'{k}' + ('(必填)' if k in tool.required_params else '') for k in tool.params_schema)
            level = f'[{tool.risk_level.value}]'
            lines.append(f'- **{tool.name}** {level}: {tool.description}')
            if tool.params_schema:
                lines.append(f'  - 参数: {params}')
            if tool.requires_read_first:
                lines.append('  - 规则: 必须先 read 再修改')
        return '\n'.join(lines)
