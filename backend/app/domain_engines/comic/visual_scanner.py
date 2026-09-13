"""漫剧视觉一致性扫描器 — 检测角色外貌/服装跨分镜一致性。

对比相邻分镜中同一角色的 appearance 描述，
检测是否存在不一致（如：分镜 1 描述"黑发"，分镜 3 变为"棕发"）。

当多模态后端可用时（MULTIMODAL_BACKEND=cloud|local），
额外对镜头图片进行视觉对比，提升检测精度。
"""

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pm.scanner_base import BaseScanner, ScanIssue

import logging

logger = logging.getLogger(__name__)


class VisualConsistencyScanner(BaseScanner):
    """角色视觉一致性扫描 — 检测跨分镜外貌变化。

    扫描策略：
    1. 文本层（始终启用）：对比 characters_visual 中的 appearance 描述
    2. 视觉层（多模态可用时）：对镜头图片进行视觉对比
    """

    name = 'visual_consistency'
    issue_type = 'ca_visual_inconsistency'

    async def scan(
        self, db: AsyncSession, project_id: str, user_id: str
    ) -> list[ScanIssue]:
        """对比相邻分镜的角色视觉描述 + 可选视觉对比。"""
        issues: list[ScanIssue] = []
        try:
            # 查最近 50 个分镜的 characters_visual 和图片 URL
            result = await db.execute(
                text("""
                    SELECT id, global_sequence, characters_visual, image_url
                    FROM comic_panels
                    WHERE project_id = :pid
                      AND characters_visual IS NOT NULL
                    ORDER BY global_sequence DESC
                    LIMIT 50
                """),
                {'pid': project_id},
            )
            rows = result.fetchall()

            # 逐对对比相邻分镜
            for i in range(len(rows) - 1):
                seq_curr, cv_curr, img_curr = rows[i][1], rows[i][2] or [], rows[i][3]
                seq_prev, cv_prev, img_prev = rows[i + 1][1], rows[i + 1][2] or [], rows[i + 1][3]

                # 构建角色 -> appearance 映射
                curr_map = {cv.get('name'): cv.get('appearance', '') for cv in cv_curr if cv.get('name')}
                prev_map = {cv.get('name'): cv.get('appearance', '') for cv in cv_prev if cv.get('name')}

                # 检测同一角色的外貌变化（文本层）
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

            # 视觉层：多模态可用时，对镜头图片做视觉对比
            if issues:
                issues.extend(await self._visual_compare_panels(rows))

        except Exception as e:
            logger.warning('[CA] 视觉一致性扫描异常 project=%s: %s', project_id, e)
        return issues

    async def _visual_compare_panels(self, rows: list) -> list[ScanIssue]:
        """多模态视觉对比（可选，失败不影响主流程）。"""
        from app.services.multimodal import get_multimodal_service

        mm = get_multimodal_service()
        if not mm.is_available:
            return []

        issues: list[ScanIssue] = []
        try:
            for i in range(len(rows) - 1):
                img_a = rows[i][3]  # image_url
                img_b = rows[i + 1][3]
                seq_a = rows[i][1]
                seq_b = rows[i + 1][1]

                if not img_a or not img_b:
                    continue

                result = await mm.compare_images(img_a, img_b)
                score = result.consistency_score

                # 写入一致性评分到 Shot 模型（供前端展示）
                try:
                    from app.models.comic_shot import Shot
                    shot_result = await db.execute(
                        select(Shot).where(
                            Shot.project_id == rows[i][0].split(':')[0] if ':' in str(rows[i][0]) else None,
                            Shot.shot_number == seq_a,
                        ).limit(1)
                    )
                    shot = shot_result.scalar_one_or_none()
                    if shot:
                        shot.last_consistency_score = score
                except Exception:
                    pass  # 非阻塞：写入失败不影响主流程

                if score < 0.7:
                    issues.append(
                        ScanIssue(
                            issue_type='ca_visual_inconsistency',
                            severity='warning',
                            message=f'分镜 {seq_b}→{seq_a} 视觉相似度低 ({score:.0%})，可能存在角色外貌不一致',
                            entities=[f'panel:{seq_b}', f'panel:{seq_a}'],
                            metadata={
                                'consistency_score': score,
                                'panel_from': seq_b,
                                'panel_to': seq_a,
                                'backend': result.backend,
                                'differences': result.issues,
                            },
                        )
                    )
        except Exception as e:
            logger.debug('[CA] 多模态视觉对比跳过（非阻塞）: %s', e)
        return issues

    def to_diagnostic_message(self, issue: ScanIssue) -> str:
        return f'[CA] {issue.message}'
