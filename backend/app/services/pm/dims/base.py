"""PM 维度基类 — 每个维度自包含 scan + fix + verify，加新维度只需加文件。"""

from abc import ABC, abstractmethod
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession


class DimensionBase(ABC):
    """维度基类：子类实现 scan/fix/verify 三个方法。"""

    name: str = ''
    issue_type: str = ''
    severity: str = 'warning'  # critical / warning / info

    @abstractmethod
    async def scan(self, db: AsyncSession, project_id: str, user_id: str) -> list[dict[str, Any]]:
        """扫描问题，返回 issue 列表。"""
        ...

    @abstractmethod
    async def fix(self, issue: dict[str, Any], project_id: str, user_id: str, db: AsyncSession) -> str:
        """修复问题，返回 fix_action 描述。"""
        ...

    async def verify(self, issue: dict[str, Any], fix_action: str, project_id: str, user_id: str, db: AsyncSession) -> tuple[bool, str]:
        """验证修复结果，返回 (passed, message)。默认实现：有 fix_action 就算通过。"""
        return (bool(fix_action), fix_action or '无修复动作')

    def diag_msg(self, issue: dict[str, Any]) -> str:
        """生成诊断消息。子类可覆盖。"""
        return f'[PM-Agent] {self.name}: {issue}'
