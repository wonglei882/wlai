"""漫剧场景连续性扫描器 — 检测场景描述跨分镜的连续性。

检测同一页内或相邻页的场景描述是否发生不合理跳变
（如：分镜 1 描述"白天"，分镜 2 突然变为"深夜"且无过渡）。
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pm.scanner_base import BaseScanner, ScanIssue

import logging

logger = logging.getLogger(__name__)

# 时间关键词冲突对（互斥的时间描述）
_TIME_CONFLICTS = {
    frozenset({'白天', '日光', '正午', '上午', '下午'}): frozenset({'深夜', '夜晚', '午夜', '凌晨'}),
    frozenset({'室内', '房间', '屋内'}): frozenset({'户外', '野外', '山顶', '海边'}),
}


class SceneContinuityScanner(BaseScanner):
    """场景连续性扫描 — 检测场景描述不合理跳变。"""

    name = 'scene_continuity'
    issue_type = 'ca_scene_discontinuity'

    async def scan(
        self, db: AsyncSession, project_id: str, user_id: str
    ) -> list[ScanIssue]:
        """检测相邻分镜的场景描述跳变。"""
        issues: list[ScanIssue] = []
        try:
            result = await db.execute(
                text("""
                    SELECT id, global_sequence, page_number, scene_description, scene_metadata
                    FROM comic_panels
                    WHERE project_id = :pid
                      AND scene_description IS NOT NULL
                    ORDER BY global_sequence DESC
                    LIMIT 20
                """),
                {'pid': project_id},
            )
            rows = result.fetchall()

            for i in range(len(rows) - 1):
                seq_curr, page_curr, scene_curr, meta_curr = rows[i][1], rows[i][2], rows[i][3] or '', rows[i][4] or {}
                seq_prev, page_prev, scene_prev, meta_prev = rows[i + 1][1], rows[i + 1][2], rows[i + 1][3] or '', rows[i + 1][4] or {}

                # 同页内场景应有连续性
                if page_curr == page_prev:
                    # 检测时间冲突
                    time_issue = self._check_time_conflict(scene_curr, scene_prev)
                    if time_issue:
                        issues.append(
                            ScanIssue(
                                issue_type='ca_scene_discontinuity',
                                severity='critical',
                                message=f'同页时间矛盾: 「{scene_prev}」→「{scene_curr}」(P{page_curr}, 分镜 {seq_prev}→{seq_curr})',
                                entities=[f'panel:{seq_prev}', f'panel:{seq_curr}'],
                                metadata={
                                    'conflict_type': 'time',
                                    'scene_from': scene_prev,
                                    'scene_to': scene_curr,
                                    'page': page_curr,
                                },
                            )
                        )

        except Exception as e:
            logger.warning('[CA] 场景连续性扫描异常 project=%s: %s', project_id, e)
        return issues

    def _check_time_conflict(self, scene_a: str, scene_b: str) -> bool:
        """检测两个场景描述中是否存在时间矛盾。"""
        for group_a, group_b in _TIME_CONFLICTS:
            has_a = any(kw in scene_a for kw in group_a)
            has_b = any(kw in scene_b for kw in group_b)
            if has_a and has_b:
                return True
            has_a = any(kw in scene_b for kw in group_a)
            has_b = any(kw in scene_a for kw in group_b)
            if has_a and has_b:
                return True
        return False

    def to_diagnostic_message(self, issue: ScanIssue) -> str:
        return f'[CA] {issue.message}'
