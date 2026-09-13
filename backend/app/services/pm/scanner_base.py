"""PM 巡检扫描器基类 — 统一 I/O 契约与标准化结果结构。

参照量子算法项目 BaseAlgorithm 设计，为巡检维度提供：
- ScanIssue: 标准化扫描结果数据类（替代裸 dict）
- BaseScanner: 抽象基类，定义 scan() + to_diagnostic_message() 接口
- ScannerAdapter: 将裸函数适配为 BaseScanner 接口（向后兼容 @scan_dimension）

新增巡检维度推荐继承 BaseScanner，也可继续使用 @scan_dimension 装饰器。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ScanIssue:
    """标准化扫描结果 — 替代裸 dict，提供类型安全的结构化输出。

    Attributes:
        issue_type: 问题类型标识（如 'character_location_jump'）
        severity: 严重级别 'critical' | 'warning' | 'info'
        message: 人类可读的问题描述
        entities: 受影响实体列表（如 ['character:张三', 'chapter:5']）
        metadata: 额外元数据（保留原始 dict 格式，兼容下游处理）
    """

    issue_type: str
    severity: str = 'warning'
    message: str = ''
    entities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为 dict（兼容下游 dict 消费逻辑）。"""
        return {
            'type': self.issue_type,
            'severity': self.severity,
            'message': self.message,
            'entities': self.entities,
            **self.metadata,
        }


class BaseScanner(ABC):
    """巡检维度抽象基类 — 标准化扫描接口。

    子类必须实现:
        - name: 维度标识（如 'character_consistency'）
        - issue_type: 诊断类型（如 'pm_agent_character_jump'）
        - scan(): 核心扫描逻辑

    子类可覆盖:
        - to_diagnostic_message(): 自定义诊断消息格式
    """

    name: str
    issue_type: str

    @abstractmethod
    async def scan(
        self, db: AsyncSession, project_id: str, user_id: str
    ) -> list[ScanIssue]:
        """执行扫描，返回问题列表。"""
        ...

    def to_diagnostic_message(self, issue: ScanIssue) -> str:
        """从 ScanIssue 生成诊断日志消息（子类可覆盖自定义格式）。"""
        return f'[PM-Agent] {issue.message}'


class ScannerAdapter(BaseScanner):
    """将裸函数适配为 BaseScanner 接口 — 用于向后兼容 @scan_dimension 注册的函数。

    Args:
        name: 维度标识
        issue_type: 诊断类型
        scan_fn: 原始扫描函数 (db, project_id, user_id) -> list[dict]
        diag_msg_fn: 从 issue dict 生成诊断消息的函数
    """

    def __init__(
        self,
        name: str,
        issue_type: str,
        scan_fn,
        diag_msg_fn,
    ):
        self.name = name
        self.issue_type = issue_type
        self._scan_fn = scan_fn
        self._diag_msg_fn = diag_msg_fn

    async def scan(
        self, db: AsyncSession, project_id: str, user_id: str
    ) -> list[ScanIssue]:
        """调用原始扫描函数，将 dict 结果转换为 ScanIssue。"""
        raw_issues = await self._scan_fn(db, project_id, user_id)
        # 裸函数返回 list[dict]，保持兼容不强制转换
        return raw_issues

    def to_diagnostic_message(self, issue: ScanIssue | dict) -> str:
        """使用原始 diag_msg_fn 生成消息。"""
        if isinstance(issue, dict):
            return self._diag_msg_fn(issue)
        return self._diag_msg_fn(issue.metadata or issue.to_dict())
