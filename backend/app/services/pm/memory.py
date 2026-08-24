"""项目主管强化版记忆系统 — 经验提炼 + 失败模式 + 偏好学习"""

from datetime import datetime
from app.logger import get_logger
from app.models.pm_v2 import ExperienceCard, FailurePattern, UserPreference
from sqlalchemy import select

logger = get_logger(__name__)


class PMMemoryV2:
    """强化版记忆系统"""

    def __init__(self, project_id: str, user_id: str, db):
        self.project_id = project_id
        self.user_id = user_id
        self.db = db

    # ============ 经验提炼 ============

    async def extract_experience(self, task_type: str, scores: dict, context: dict) -> str:
        """从高分案例中提炼经验并存储为经验卡片"""
        try:
            card = ExperienceCard(
                project_id=self.project_id,
                task_type=task_type,
                pattern=self._build_pattern(scores, context),
                success_conditions=f'评分>{scores.get("total_score", 70)}/100',
                context_patterns={'task_type': task_type, 'dimensions': list(scores.keys())},
                source_scores=scores,
            )
            self.db.add(card)
            await self.db.commit()
            return card.pattern[:200]
        except Exception as e:
            logger.warning(f'经验提炼失败: {e}')
            await self.db.rollback()
            return ''

    def _build_pattern(self, scores: dict, context: dict) -> str:
        """构建Pattern

        Args:
            self:
            scores:
            context:

        Returns:
            str
        """
        high = [k for k, v in scores.items() if isinstance(v, (int, float)) and v >= 80]
        low = [k for k, v in scores.items() if isinstance(v, (int, float)) and v < 60]
        parts = []
        if high:
            parts.append(f'优势维度: {", ".join(high)}')
        if low:
            parts.append(f'需改进: {", ".join(low)}')
        parts.append(f'输入特征: 字数={context.get("input_length", "unknown")}')
        return '; '.join(parts)

    async def get_relevant_experience(self, task_type: str, limit: int = 3) -> list:
        """获取相关经验卡片"""
        try:
            r = await self.db.execute(
                select(ExperienceCard)
                .where(
                    ExperienceCard.project_id == self.project_id,
                    ExperienceCard.task_type == task_type,
                )
                .order_by(ExperienceCard.success_rate.desc())
                .limit(limit)
            )
            return r.scalars().all()
        except Exception as e:
            logger.warning(f'获取经验失败: {e}')
            return []

    # ============ 失败模式 ============

    async def register_failure(self, task_type: str, error: str, pattern_type: str = 'execution_error'):
        """QS1：注册失败模式（key 统一加 mem_ 前缀，避免与 self_tuning 的
        `tune_{tool}:{error_type}` 格式撞命名空间、导致同问题被记成两条）。"""
        # 统一命名空间前缀
        full_key = pattern_type if pattern_type.startswith(('mem_', 'tune_')) else f'mem_{pattern_type}'
        try:
            # 查重：同类型+同错误已存在则计数+1
            r = await self.db.execute(
                select(FailurePattern)
                .where(
                    FailurePattern.project_id == self.project_id,
                    FailurePattern.pattern_type == full_key,
                    FailurePattern.error_description.contains(error[:100]),
                )
                .limit(1)
            )
            existing = r.scalar_one_or_none()
            if existing:
                existing.occurrence_count = (existing.occurrence_count or 1) + 1
                existing.last_occurred_at = datetime.now()
            else:
                self.db.add(
                    FailurePattern(
                        project_id=self.project_id,
                        pattern_type=full_key,
                        error_description=error[:500],
                        root_cause='',
                        recovery_suggestion='',
                    )
                )
            await self.db.commit()
        except Exception as e:
            logger.warning(f'注册失败模式失败: {e}')
            await self.db.rollback()

    async def check_warnings(self, task_type: str, threshold: int = 3) -> list[str]:
        """检查高频失败模式，超过阈值返回预警"""
        warnings = []
        try:
            r = await self.db.execute(
                select(FailurePattern)
                .where(
                    FailurePattern.project_id == self.project_id,
                    FailurePattern.pattern_type == task_type,
                    FailurePattern.occurrence_count >= threshold,
                )
                .order_by(FailurePattern.occurrence_count.desc())
                .limit(5)
            )
            for fp in r.scalars().all():
                warnings.append(f'⚠️ [{fp.pattern_type}] 已出现{fp.occurrence_count}次: {fp.error_description[:60]}')
        except Exception as e:
            logger.warning(f'[pm_memory_v2] check_warnings 失败: {e}')
        return warnings

    # ============ 偏好学习 ============

    async def learn_preference(self, preference_type: str, value: dict, confidence: float = 0.5, source: str = 'feedback'):
        """Q2：学习用户偏好（统一入口：委托 pm_preference_learner._upsert_preference）。

        之前 memory.learn_preference 与 pm_preference_learner.learn_from_feedback
        对同一张 UserPreference 表使用两套不同置信度更新公式，时间一长会交替
        覆盖、置信度断裂。修复后后者是唯一写入方。
        """
        from app.services.pm.pm_preference_learner import _upsert_preference

        try:
            import json as _json_pref

            # content：value 若是 dict 且有 content 则优先使用，否则序列化摘要
            content = value.get('content') if isinstance(value, dict) else None
            if not content:
                content = _json_pref.dumps(value, ensure_ascii=False)[:200]
            await _upsert_preference(
                self.db,
                self.user_id,
                self.project_id,
                preference_type,
                content,
                source,
            )
        except Exception as e:
            logger.warning(f'偏好学习失败: {e}')
            await self.db.rollback()

    async def get_preferences(self) -> dict:
        """获取用户偏好汇总"""
        prefs = {}
        try:
            r = await self.db.execute(
                select(UserPreference)
                .where(
                    UserPreference.project_id == self.project_id,
                    UserPreference.user_id == self.user_id,
                )
                .order_by(UserPreference.confidence.desc())
            )
            for up in r.scalars().all():
                prefs[up.preference_type] = {'value': up.value, 'confidence': up.confidence, 'source': up.source}
        except Exception as e:
            logger.warning(f'[pm_memory_v2] get_preferences 失败: {e}')
        return prefs
