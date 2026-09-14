"""PM 维度基类 — 每个维度自包含 scan + fix + verify，加新维度只需加文件。

三层架构中的「执行层」抽象：
- 统一 DimensionBase 作为所有扫描/修复/验证维度的基类
- scan() 返回 list[ScanIssue]（结构化输出，兼容 dict 适配）
- fix() 返回 fix_action 描述
- verify() 返回 (passed, message)

与 scanner_base.py 的关系：
- ScanIssue 定义在 scanner_base.py 中，此处 re-export 保持单一事实来源
- BaseScanner 定义在 scanner_base.py（接口与 DimensionBase 对齐：name/issue_type/scan）
- 两个抽象面向不同侧重点：DimensionBase 侧重 scan+fix+verify 三方法闭环，
  BaseScanner 侧重扫描器标准接口 + to_diagnostic_message 扩展
"""

from abc import ABC, abstractmethod
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

# Re-export ScanIssue（保持单一事实来源在 scanner_base.py）
from app.services.pm.scanner_base import ScanIssue as ScanIssue  # noqa: F401


class DimensionBase(ABC):
    """维度基类：子类实现 scan/fix/verify 三个方法。

    scan() 返回 ScanIssue 列表（推荐）或 dict 列表（向后兼容），
    fix() 返回修复动作描述字符串，
    verify() 返回 (passed, message) 元组。
    """

    name: str = ''
    issue_type: str = ''
    severity: str = 'warning'  # critical / warning / info

    @abstractmethod
    async def scan(self, db: AsyncSession, project_id: str, user_id: str) -> list[Any]:
        """扫描问题，返回 ScanIssue 列表（或兼容的 dict 列表）。"""
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
