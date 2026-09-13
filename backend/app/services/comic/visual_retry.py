"""视觉一致性自动重试闭环。

当 VisualConsistencyScanner 检测到角色变脸/画风割裂时：
1. 检查重试次数（上限 3 次）
2. 回退镜头状态为 pending_image
3. 注入修正提示词（强化角色外貌描述 + 固定 seed）
4. 记录重试日志
5. 超过上限转人工审核

遵循项目编码规范：异常 try/except 吞掉，仅记录日志，不中断主流程。
"""

from typing import Any
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 3
CONFIDENCE_THRESHOLD = 0.75


class VisualRetryService:
    """视觉一致性自动重试服务。"""

    async def handle_visual_issue(
        self,
        db: AsyncSession,
        issue: dict[str, Any],
        project_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """处理视觉一致性问题，触发自动重试。

        Args:
            db: 数据库会话
            issue: 扫描器产出的问题字典（含 metadata）
            project_id: 项目 ID
            user_id: 用户 ID

        Returns:
            {'action': 'retry'|'escalate'|'skip', ...}
        """
        try:
            metadata = issue.get('metadata', {})
            panel_from = metadata.get('panel_from')
            panel_to = metadata.get('panel_to')
            character_name = metadata.get('character', '')
            consistency_score = metadata.get('consistency_score')

            if not panel_to:
                return {'action': 'skip', 'reason': '无目标镜头信息'}

            # 1. 查找目标 Shot（通过 storyboard_id + shot_number 或 comic_shots 直接查）
            shot = await self._find_shot_by_panel(db, project_id, panel_to)
            if not shot:
                return {'action': 'skip', 'reason': f'未找到镜头 panel={panel_to}'}

            # 2. 检查重试次数
            current_retry = shot.retry_count or 0
            if current_retry >= MAX_RETRY_ATTEMPTS:
                logger.info(
                    '[VisualRetry] 镜头 %s 已达最大重试次数 %d，转人工',
                    shot.id[:8], MAX_RETRY_ATTEMPTS,
                )
                return {
                    'action': 'escalate',
                    'reason': f'超过最大重试次数({MAX_RETRY_ATTEMPTS})',
                    'shot_id': shot.id,
                    'retry_count': current_retry,
                }

            # 3. 写入一致性评分
            if consistency_score is not None:
                shot.last_consistency_score = float(consistency_score)

            # 4. 构建修正提示词
            corrected_prompt = await self._build_corrected_prompt(
                db, project_id, character_name, metadata
            )
            shot.corrected_prompt = corrected_prompt

            # 5. 回退状态为 pending_image（重新出图）
            if shot.status in ('pending_review_image', 'pending_image'):
                shot.status = 'pending_image'
            elif shot.status not in ('pending_script', 'pending_image'):
                # 已在后续状态的视频/配音等，不回退
                return {'action': 'skip', 'reason': f'镜头状态 {shot.status} 不适合回退'}

            # 6. 递增重试计数
            shot.retry_count = current_retry + 1

            await db.commit()

            logger.info(
                '[VisualRetry] 镜头 %s 触发第 %d 次重试 (角色=%s, 评分=%.2f)',
                shot.id[:8], shot.retry_count, character_name,
                consistency_score or 0,
            )

            return {
                'action': 'retry',
                'shot_id': shot.id,
                'attempt': shot.retry_count,
                'corrected_prompt': corrected_prompt,
                'previous_score': consistency_score,
            }

        except Exception as e:
            logger.warning('[VisualRetry] 处理异常（非阻塞）: %s', e)
            try:
                await db.rollback()
            except Exception:
                pass
            return {'action': 'skip', 'reason': f'处理异常: {e}'}

    async def _find_shot_by_panel(
        self, db: AsyncSession, project_id: str, panel_seq: Any
    ) -> Any:
        """通过分镜序号查找对应的 Shot。"""
        from app.models.comic_shot import Shot

        try:
            # 优先按 shot_number 匹配
            result = await db.execute(
                select(Shot).where(
                    Shot.project_id == project_id,
                    Shot.shot_number == int(panel_seq),
                ).limit(1)
            )
            return result.scalar_one_or_none()
        except (ValueError, TypeError):
            return None

    async def _build_corrected_prompt(
        self,
        db: AsyncSession,
        project_id: str,
        character_name: str,
        metadata: dict[str, Any],
    ) -> str:
        """构建修正提示词 — 强化角色外貌描述。

        从角色卡中获取固定外貌提示词，追加到原始提示词中。
        """
        try:
            from app.models.comic_bible import CharacterCard

            # 查找角色卡
            if character_name:
                result = await db.execute(
                    select(CharacterCard).where(
                        CharacterCard.project_id == project_id,
                        CharacterCard.name == character_name,
                    ).limit(1)
                )
                char_card = result.scalar_one_or_none()
                if char_card and char_card.appearance_prompt:
                    # 强化外貌描述
                    appearance = char_card.appearance_prompt
                    parts = [appearance]
                    if char_card.hair:
                        parts.append(f'hair: {char_card.hair}')
                    if char_card.eyes:
                        parts.append(f'eyes: {char_card.eyes}')
                    if char_card.outfit:
                        parts.append(f'outfit: {char_card.outfit}')
                    return f'[VISUAL_CORRECTION] Character "{character_name}" appearance must match exactly: {", ".join(parts)}'

            # 通用修正
            appearance_from = metadata.get('appearance_from', '')
            appearance_to = metadata.get('appearance_to', '')
            if appearance_from and appearance_to:
                return (
                    f'[VISUAL_CORRECTION] Ensure character appearance is consistent. '
                    f'Expected: "{appearance_from}", got: "{appearance_to}". '
                    f'Use the expected appearance description.'
                )

            return '[VISUAL_CORRECTION] Ensure visual consistency with previous panels. Maintain same character appearance, art style, and color palette.'

        except Exception as e:
            logger.debug('[VisualRetry] 构建修正提示词失败: %s', e)
            return '[VISUAL_CORRECTION] Ensure visual consistency with previous panels.'
