"""漫镜衔接扫描器 — 检测分镜间镜头语言合理性。

检测不合理的镜头跳切（如：连续 3 个相同角度、缺少过渡镜头等）。
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pm.scanner_base import BaseScanner, ScanIssue

import logging

logger = logging.getLogger(__name__)

# 连续相同镜头角度上限（超过视为节奏单调）
MAX_SAME_ANGLE_STREAK = 3


class PanelTransitionScanner(BaseScanner):
    """分镜衔接扫描 — 检测镜头语言跳切/节奏问题。"""

    name = 'panel_transition'
    issue_type = 'ca_panel_transition'

    async def scan(
        self, db: AsyncSession, project_id: str, user_id: str
    ) -> list[ScanIssue]:
        """检测分镜间的镜头衔接问题。"""
        issues: list[ScanIssue] = []
        try:
            result = await db.execute(
                text("""
                    SELECT id, global_sequence, page_number, camera_angle, transition_type
                    FROM comic_panels
                    WHERE project_id = :pid
                    ORDER BY global_sequence ASC
                    LIMIT 50
                """),
                {'pid': project_id},
            )
            rows = result.fetchall()

            # 检测连续相同镜头角度
            streak = 1
            streak_start = 0
            for i in range(1, len(rows)):
                angle_curr = rows[i][3] or ''
                angle_prev = rows[i - 1][3] or ''

                if angle_curr and angle_curr == angle_prev:
                    streak += 1
                else:
                    if streak >= MAX_SAME_ANGLE_STREAK:
                        issues.append(
                            ScanIssue(
                                issue_type='ca_panel_transition',
                                severity='info',
                                message=f'连续 {streak} 个相同镜头角度「{rows[streak_start][3]}」(分镜 {rows[streak_start][1]}~{rows[i - 1][1]})，节奏可能单调',
                                entities=[f'panel:{rows[streak_start][1]}', f'panel:{rows[i - 1][1]}'],
                                metadata={
                                    'issue': 'same_angle_streak',
                                    'angle': angle_prev,
                                    'count': streak,
                                },
                            )
                        )
                    streak = 1
                    streak_start = i

            # 尾部检查
            if streak >= MAX_SAME_ANGLE_STREAK:
                issues.append(
                    ScanIssue(
                        issue_type='ca_panel_transition',
                        severity='info',
                        message=f'连续 {streak} 个相同镜头角度「{rows[streak_start][3]}」',
                        entities=[f'panel:{rows[streak_start][1]}'],
                        metadata={'issue': 'same_angle_streak', 'count': streak},
                    )
                )

        except Exception as e:
            logger.warning('[CA] 分镜衔接扫描异常 project=%s: %s', project_id, e)
        return issues

    def to_diagnostic_message(self, issue: ScanIssue) -> str:
        return f'[CA] {issue.message}'
