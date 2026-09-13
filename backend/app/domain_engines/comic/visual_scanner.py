"""漫剧视觉一致性扫描器 — 检测角色外貌/服装跨分镜一致性。

对比相邻分镜中同一角色的 appearance 描述，
检测是否存在不一致（如：分镜 1 描述"黑发"，分镜 3 变为"棕发"）。
"""

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pm.scanner_base import BaseScanner, ScanIssue

import logging

logger = logging.getLogger(__name__)


class VisualConsistencyScanner(BaseScanner):
    """角色视觉一致性扫描 — 检测跨分镜外貌变化。"""

    name = 'visual_consistency'
    issue_type = 'ca_visual_inconsistency'

    async def scan(
        self, db: AsyncSession, project_id: str, user_id: str
    ) -> list[ScanIssue]:
        """对比相邻分镜的角色视觉描述。"""
        issues: list[ScanIssue] = []
        try:
            # 查最近 20 个分镜的 characters_visual
            result = await db.execute(
                text("""
                    SELECT id, global_sequence, characters_visual
                    FROM comic_panels
                    WHERE project_id = :pid
                      AND characters_visual IS NOT NULL
                    ORDER BY global_sequence DESC
                    LIMIT 20
                """),
                {'pid': project_id},
            )
            rows = result.fetchall()

            # 逐对对比相邻分镜
            for i in range(len(rows) - 1):
                seq_curr, cv_curr = rows[i][1], rows[i][2] or []
                seq_prev, cv_prev = rows[i + 1][1], rows[i + 1][2] or []

                # 构建角色 -> appearance 映射
                curr_map = {cv.get('name'): cv.get('appearance', '') for cv in cv_curr if cv.get('name')}
                prev_map = {cv.get('name'): cv.get('appearance', '') for cv in cv_prev if cv.get('name')}

                # 检测同一角色的外貌变化
                for name in set(curr_map.keys()) & set(prev_map.keys()):
                    curr_app = curr_map[name]
                    prev_app = prev_map[name]
                    if curr_app and prev_app and curr_app != prev_app:
                        issues.append(
                            ScanIssue(
                                issue_type='ca_visual_inconsistency',
                                severity='warning',
                                message=f'角色「{name}」外貌变化: 「{prev_app}」→「{curr_app}」(分镜 {seq_prev}→{seq_curr})',
                                entities=[f'character:{name}', f'panel:{seq_prev}', f'panel:{seq_curr}'],
                                metadata={
                                    'character': name,
                                    'appearance_from': prev_app,
                                    'appearance_to': curr_app,
                                    'panel_from': seq_prev,
                                    'panel_to': seq_curr,
                                },
                            )
                        )

        except Exception as e:
            logger.warning('[CA] 视觉一致性扫描异常 project=%s: %s', project_id, e)
        return issues

    def to_diagnostic_message(self, issue: ScanIssue) -> str:
        return f'[CA] {issue.message}'
