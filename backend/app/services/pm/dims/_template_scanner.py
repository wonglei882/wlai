"""新增巡检维度模板 — 复制此文件并重命名即可。

步骤:
1. 复制本文件为 `scan_xxx.py`（如 `scan_emotion_shift.py`）
2. 继承 BaseScanner，实现 scan() 方法
3. 在 pm_scanners.py 的 SCAN_REGISTRY 中注册（或使用 @scan_dimension 装饰器）
4. 在 pm_features.yaml 的 core.inspection.dimensions 中添加维度名
5. 在 pm_features.yaml 的 scanner_params 中声明该维度参数

示例:
    class EmotionShiftScanner(BaseScanner):
        name = 'emotion_shift'
        issue_type = 'pm_agent_emotion_shift'

        async def scan(self, db, project_id, user_id):
            issues = []
            # ... 扫描逻辑
            return issues
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pm.scanner_base import BaseScanner, ScanIssue


class TemplateScanner(BaseScanner):
    """巡检维度模板 — 复制后修改 name / issue_type / scan() 即可。"""

    name = 'template_dimension'
    issue_type = 'pm_agent_template_issue'

    async def scan(
        self, db: AsyncSession, project_id: str, user_id: str
    ) -> list[ScanIssue]:
        """核心扫描逻辑 — 子类必须实现。

        实现要点:
        - 使用 _get_param(self.name, 'key', fallback) 读取声明式参数
        - 异常统一 try/except + logger.warning，不向上抛出
        - 返回 ScanIssue 列表（或 dict 列表，兼容下游）
        """
        issues: list[ScanIssue] = []
        try:
            # TODO: 实现扫描逻辑
            pass
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                '[PM-Agent] %s 扫描异常 project=%s: %s', self.name, project_id, e
            )
        return issues

    def to_diagnostic_message(self, issue: ScanIssue) -> str:
        """生成诊断日志消息 — 子类可覆盖自定义格式。"""
        return f'[PM-Agent] 模板维度: {issue.message}'
