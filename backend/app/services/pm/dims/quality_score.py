"""质量评分维度 — scan + fix 自包含。"""

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.services.pm.dims.base import DimensionBase


class QualityScoreDimension(DimensionBase):
    name = 'quality_score'
    issue_type = 'pm_agent_quality_score_low'
    severity = 'critical'
    THRESHOLD = 70

    async def scan(self, db: AsyncSession, project_id: str, user_id: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        try:
            result = await db.execute(
                text("""
                    SELECT id, chapter_number, content FROM chapters
                    WHERE project_id = :pid AND content IS NOT NULL AND length(content) > 200
                    ORDER BY chapter_number DESC LIMIT 1
                """),
                {'pid': project_id},
            )
            row = result.fetchone()
            if not row:
                return issues
            chapter_id, chapter_number, content = row[0], row[1], row[2] or ''

            ai = None
            try:
                from app.services.pm.pm_ai_client import get_pm_ai_client

                ai = await get_pm_ai_client(user_id, db)
            except Exception:  # noqa: S110  AI客户端获取失败时降级为None，评分器走无AI规则路径
                pass

            from app.services.pm.quality_scorer import PMQualityScorerV2

            scorer = PMQualityScorerV2(ai_service=ai)
            score_result = await scorer.score(content, context={})

            if not score_result.passed:
                low_dims = [dim for dim, sc in score_result.scores.items() if sc < 60]
                issues.append(
                    {
                        'type': 'quality_score_low',
                        'chapter_number': chapter_number,
                        'chapter_id': str(chapter_id),
                        'total_score': score_result.total_score,
                        'low_dims': low_dims,
                        'suggestions': score_result.suggestions,
                    }
                )
        except Exception:  # noqa: S110  质量评分属巡检附属检查，异常不得中断PM巡检主流程
            pass
        return issues

    async def fix(self, issue: dict[str, Any], project_id: str, user_id: str, db: AsyncSession) -> str:
        # 复用现有的 _fix_quality_low 逻辑
        from app.services.pm.pm_fix_executors import _fix_quality_low

        return await _fix_quality_low(issue, project_id, user_id, db)

    def diag_msg(self, issue: dict[str, Any]) -> str:
        return f'[PM-Agent] 第{issue.get("chapter_number", "?")}章质量评分 {issue.get("total_score", 0):.1f} < {self.THRESHOLD}'
