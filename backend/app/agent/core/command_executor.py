"""PM 工具执行器（独立部署补齐）。

解析 `[TOOL:name|k=v&k2=v2]` 命令文本 → 从 registry 查找工具 → 调用 handler。

handler 调用约定（按签名自动适配）：
- 约定 1（推荐）：`async def handler(params: dict, db, user_id='', project_id=None)` —— 首个参数名必须是 `params`
- 约定 2：`async def handler(**named_args)` —— 按参数名传参，并自动注入 db/user_id/project_id
"""
import asyncio
import inspect
import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_TOOL_RE = re.compile(r'\[TOOL:([^\|\]]+)(?:\|([^\]]*))?\]', re.IGNORECASE)


@dataclass
class ToolExecutionResult:
    """单次工具执行的结果。"""

    tool_name: str
    success: bool = True
    logs: list[str] = field(default_factory=list)
    error: str = ''


class CommandExecutor:
    """执行文本格式的工具命令。"""

    def __init__(self, registry, db=None, user_id='', project_id=None):
        self.registry = registry
        self.db = db
        self.user_id = user_id
        self.project_id = project_id

    async def execute_text(self, cmd_text: str) -> list[ToolExecutionResult]:
        """执行一条（或第一条匹配的）工具命令。"""
        match = _TOOL_RE.search(cmd_text or '')
        if not match:
            return [
                ToolExecutionResult(
                    tool_name='',
                    success=False,
                    logs=['无法解析工具命令，期望格式: [TOOL:name|k=v&...]'],
                    error='parse_error',
                )
            ]

        name = match.group(1).strip()
        param_str = match.group(2) or ''
        tool = self.registry.get(name)
        if tool is None:
            return [
                ToolExecutionResult(
                    tool_name=name,
                    success=False,
                    logs=[f'未注册工具: {name}'],
                    error='unknown_tool',
                )
            ]

        params = self._parse_params(param_str, tool)
        try:
            result = await self._invoke(tool.handler, params)
            logs = self._to_logs(result)
            return [ToolExecutionResult(tool_name=name, success=True, logs=logs)]
        except Exception as e:  # noqa: BLE001 - 工具异常统一转结果
            logger.exception('工具执行失败: %s', name)
            return [
                ToolExecutionResult(
                    tool_name=name,
                    success=False,
                    logs=[f'{name} 执行失败: {e}'],
                    error=str(e),
                )
            ]

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _parse_params(self, param_str: str, tool) -> dict:
        params: dict = {}
        for kv in param_str.split('&'):
            if not kv or '=' not in kv:
                continue
            k, v = kv.split('=', 1)
            hint = tool.param_types.get(k.strip()) if tool.param_types else None
            params[k.strip()] = self._coerce(v, hint)
        return params

    @staticmethod
    def _coerce(value: str, type_hint):
        """按 param_types 提示将字符串参数转为基础类型。"""
        if not type_hint:
            return value
        hint = str(type_hint).lower()
        try:
            if hint in ('int', 'integer'):
                return int(value)
            if hint == 'float':
                return float(value)
            if hint == 'bool':
                return value.lower() in ('1', 'true', 'yes', 'on')
            if hint in ('list', 'list[str]'):
                if isinstance(value, str) and value.strip().startswith('['):
                    return json.loads(value)
                return [value]
            if hint in ('dict', 'json'):
                return json.loads(value)
        except (ValueError, json.JSONDecodeError):
            return value
        return value

    async def _invoke(self, handler, params: dict):
        sig = inspect.signature(handler)
        pnames = list(sig.parameters)
        if pnames and pnames[0] == 'params':
            # 约定 1：handler(params, db[, user_id, project_id])
            kwargs = {}
            for key in ('db', 'user_id', 'project_id'):
                if key in pnames:
                    kwargs[key] = getattr(self, key)
            result = handler(params, **kwargs)
        else:
            # 约定 2：handler(**named_args)
            call_params = dict(params)
            if self.project_id is not None:
                call_params.setdefault('project_id', self.project_id)
            for key in ('db', 'user_id'):
                if key in pnames:
                    call_params[key] = getattr(self, key)
            result = handler(**call_params)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    @staticmethod
    def _to_logs(result) -> list[str]:
        if isinstance(result, list):
            return [str(x) for x in result]
        if isinstance(result, dict):
            return [json.dumps(result, ensure_ascii=False, default=str)]
        if result is None:
            return []
        return [str(result)]
