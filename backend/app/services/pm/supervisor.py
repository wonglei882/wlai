"""PM 监督层抽象 — 只审核不修改（参考 ToonFlow 监督层设计）。

三层架构中的「监督层」：
- Supervisor 负责对 issue 及修复结果进行审核，生成 AuditReport
- 严格只读：不修改任何业务数据，只产出审核结论与建议
- 审核报告供决策层决定：自动修复 / 转人工 / 跳过

核心产出物：
- AuditIssue: 单条审核问题（严重级别 / 审核项 / 问题描述 / 建议 / 红线）
- AuditReport: 完整审核报告（评分 / 总评 / issue 列表 / passed 判定）
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AuditIssue:
    """监督层审核问题 — 单条审核结论。

    Attributes:
        severity: 严重级别 'critical' | 'warning' | 'info'
        check_item: 审核项名称（如 'red_line_violation' / 'fix_result'）
        problem: 问题描述
        suggestion: 建议方案（多选用 / 分隔）
        red_line_id: 命中红线 ID（未命中红线为 None）
    """

    severity: str = 'warning'
    check_item: str = ''
    problem: str = ''
    suggestion: str = ''
    red_line_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（供 API / 前端展示）。"""
        return {
            'severity': self.severity,
            'check_item': self.check_item,
            'problem': self.problem,
            'suggestion': self.suggestion,
            'red_line_id': self.red_line_id,
        }


@dataclass
class AuditReport:
    """监督层审核报告 — 完整的审核产出物。

    Attributes:
        score: 综合评分 'A' | 'B' | 'C' | 'D'
        summary: 总评（人类可读）
        issues: 审核问题列表
    """

    score: str = 'B'
    summary: str = ''
    issues: list[AuditIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（供 API / 前端展示）。"""
        return {
            'score': self.score,
            'summary': self.summary,
            'issues': [i.to_dict() for i in self.issues],
            'passed': self.passed,
        }

    @property
    def passed(self) -> bool:
        """审核是否通过 — 无 critical 问题且无红线命中才算通过。"""
        for issue in self.issues:
            if issue.severity == 'critical' or issue.red_line_id:
                return False
        return True

    def add_issue(self, issue: AuditIssue) -> 'AuditReport':
        """追加一条审核问题（链式调用）。"""
        self.issues.append(issue)
        return self

    def has_red_line(self) -> bool:
        """是否命中红线。"""
        return any(i.red_line_id for i in self.issues)


class Supervisor(ABC):
    """监督层抽象基类 — 只审核不修改数据。

    子类必须实现:
        - name: 监督器标识（如 'verify_supervisor'）
        - audit(): 对 issue 前置审核
        - audit_fix_result(): 对修复结果审核

    设计原则：
    - audit 方法返回 AuditReport，绝不修改任何表数据
    - 审核结论（passed / 红线命中）由决策层消费，决定后续动作
    """

    name: str = ''

    @abstractmethod
    async def audit(
        self,
        issue: dict[str, Any],
        project_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> AuditReport:
        """对单个 issue 进行前置审核，返回 AuditReport。

        纯审查：检查 issue 严重性、红线标记、上下文完整性等。
        不修改任何数据。
        """
        ...

    @abstractmethod
    async def audit_fix_result(
        self,
        issue: dict[str, Any],
        fix_action: str,
        project_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> AuditReport:
        """对修复结果进行审核，返回 AuditReport。

        审核 fix_action 是否完整、是否有失败特征、是否偏离原目标。
        不修改任何数据。
        """
        ...


# =============================================================================
# 全局监督器注册表（数据驱动：新增监督器只需注册）
# =============================================================================

_SUPERVISOR_REGISTRY: dict[str, Supervisor] = {}


def register_supervisor(sup: Supervisor) -> None:
    """注册监督器实例。"""
    _SUPERVISOR_REGISTRY[sup.name] = sup


def get_supervisor(name: str) -> Supervisor | None:
    """按名称获取监督器。"""
    return _SUPERVISOR_REGISTRY.get(name)


def get_all_supervisors() -> dict[str, Supervisor]:
    """获取全部已注册监督器。"""
    return dict(_SUPERVISOR_REGISTRY)