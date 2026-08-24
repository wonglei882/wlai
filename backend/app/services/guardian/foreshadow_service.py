"""伏笔管理服务 - 处理伏笔的CRUD和业务逻辑"""

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, func, delete, update
from datetime import datetime
import uuid

from app.models.foreshadow import Foreshadow
from app.models.chapter import Chapter
from app.models.memory import PlotAnalysis, StoryMemory
from app.models.project import Project
from app.services.memory_service import memory_service
from app.schemas.foreshadow import ForeshadowCreate, ForeshadowUpdate, PlantForeshadowRequest, ResolveForeshadowRequest, SyncFromAnalysisRequest
from app.logger import get_logger
from app.services._foreshadow_helpers import generate_stable_foreshadow_id

logger = get_logger(__name__)


from app.services.guardian.foreshadow_sync_mixin import ForeshadowSyncMixin  # noqa: E402


class ForeshadowService(ForeshadowSyncMixin):
    """伏笔管理服务"""

    async def get_project_foreshadows(
        self,
        db: AsyncSession,
        project_id: str,
        status: str | None = None,
        category: str | None = None,
        source_type: str | None = None,
        is_long_term: bool | None = None,
        page: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        获取项目伏笔列表

        Args:
            db: 数据库会话
            project_id: 项目ID
            status: 状态筛选
            category: 分类筛选
            source_type: 来源筛选
            is_long_term: 是否长线伏笔
            page: 页码
            limit: 每页数量

        Returns:
            包含列表和统计的字典
        """
        try:
            # 构建查询条件
            conditions = [Foreshadow.project_id == project_id]

            if status:
                conditions.append(Foreshadow.status == status)
            if category:
                conditions.append(Foreshadow.category == category)
            if source_type:
                conditions.append(Foreshadow.source_type == source_type)
            if is_long_term is not None:
                conditions.append(Foreshadow.is_long_term == is_long_term)

            # 查询总数
            count_query = select(func.count(Foreshadow.id)).where(and_(*conditions))
            total_result = await db.execute(count_query)
            total = total_result.scalar() or 0

            # 查询列表
            query = (
                select(Foreshadow)
                .where(and_(*conditions))
                .order_by(Foreshadow.plant_chapter_number.asc().nulls_last(), desc(Foreshadow.importance), desc(Foreshadow.created_at))
                .offset((page - 1) * limit)
                .limit(limit)
            )

            result = await db.execute(query)
            foreshadows = result.scalars().all()

            # 获取统计
            stats = await self.get_stats(db, project_id)

            return {'total': total, 'items': [f.to_dict() for f in foreshadows], 'stats': stats}

        except Exception as e:
            logger.error(f'❌ 获取伏笔列表失败: {str(e)}')
            raise

    async def get_foreshadow(self, db: AsyncSession, foreshadow_id: str) -> Foreshadow | None:
        """获取单个伏笔"""
        result = await db.execute(select(Foreshadow).where(Foreshadow.id == foreshadow_id))
        return result.scalar_one_or_none()

    async def create_foreshadow(self, db: AsyncSession, data: ForeshadowCreate) -> Foreshadow:
        """
        创建伏笔

        Args:
            db: 数据库会话
            data: 创建数据

        Returns:
            创建的伏笔对象
        """
        try:
            foreshadow = Foreshadow(
                id=str(uuid.uuid4()),
                project_id=data.project_id,
                title=data.title,
                content=data.content,
                hint_text=data.hint_text,
                resolution_text=data.resolution_text,
                source_type='manual',
                plant_chapter_number=data.plant_chapter_number,
                target_resolve_chapter_number=data.target_resolve_chapter_number,
                status='pending',
                is_long_term=data.is_long_term,
                importance=data.importance,
                strength=data.strength,
                subtlety=data.subtlety,
                urgency=0,
                related_characters=data.related_characters,
                tags=data.tags,
                category=data.category,
                notes=data.notes,
                resolution_notes=data.resolution_notes,
                auto_remind=data.auto_remind,
                remind_before_chapters=data.remind_before_chapters,
                include_in_context=data.include_in_context,
            )

            db.add(foreshadow)
            await db.commit()
            await db.refresh(foreshadow)

            logger.info(f'✅ 创建伏笔成功: {foreshadow.title}')
            return foreshadow

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 创建伏笔失败: {str(e)}')
            raise

    async def update_foreshadow(self, db: AsyncSession, foreshadow_id: str, data: ForeshadowUpdate) -> Foreshadow | None:
        """
        更新伏笔

        Args:
            db: 数据库会话
            foreshadow_id: 伏笔ID
            data: 更新数据

        Returns:
            更新后的伏笔对象
        """
        try:
            foreshadow = await self.get_foreshadow(db, foreshadow_id)
            if not foreshadow:
                return None

            # 更新字段
            update_data = data.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                if hasattr(foreshadow, key):
                    setattr(foreshadow, key, value)

            await db.commit()
            await db.refresh(foreshadow)

            logger.info(f'✅ 更新伏笔成功: {foreshadow.title}')
            return foreshadow

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 更新伏笔失败: {str(e)}')
            raise

    async def delete_foreshadow(self, db: AsyncSession, foreshadow_id: str) -> bool:
        """删除伏笔,并同步清理关联记忆数据和历史分析引用"""
        try:
            foreshadow = await self.get_foreshadow(db, foreshadow_id)
            if not foreshadow:
                return False

            project_result = await db.execute(select(Project).where(Project.id == foreshadow.project_id))
            project = project_result.scalar_one_or_none()

            deleted_memory_rows = 0
            deleted_vector_memories = 0
            cleaned_analysis_refs = 0
            cleaned_analysis_rows = 0
            foreshadow_keywords = []
            content_snippet = (foreshadow.content or '')[:50].strip()

            if foreshadow.title and foreshadow.title.strip():
                foreshadow_keywords.append(foreshadow.title.strip())

            if content_snippet:
                foreshadow_keywords.append(content_snippet)

            memory_conditions = [StoryMemory.project_id == foreshadow.project_id, StoryMemory.memory_type == 'foreshadow']
            keyword_conditions = []
            for keyword in foreshadow_keywords:
                keyword_conditions.append(StoryMemory.content.contains(keyword))
                keyword_conditions.append(StoryMemory.title.contains(keyword))

            if keyword_conditions:
                delete_memory_query = delete(StoryMemory).where(and_(*memory_conditions, or_(*keyword_conditions)))
                delete_memory_result = await db.execute(delete_memory_query)
                deleted_memory_rows = delete_memory_result.rowcount or 0

            if project and project.user_id and foreshadow_keywords:
                deleted_vector_memories = await memory_service.delete_foreshadow_memories(
                    user_id=project.user_id, project_id=foreshadow.project_id, foreshadow_keywords=foreshadow_keywords
                )

            analysis_result = await db.execute(select(PlotAnalysis).where(PlotAnalysis.project_id == foreshadow.project_id))
            project_analyses = analysis_result.scalars().all()

            for analysis in project_analyses:
                analysis_foreshadows = analysis.foreshadows or []
                if not analysis_foreshadows:
                    continue

                original_count = len(analysis_foreshadows)
                filtered_foreshadows = []
                removed_count = 0

                for item in analysis_foreshadows:
                    if not isinstance(item, dict):
                        filtered_foreshadows.append(item)
                        continue

                    should_remove = False

                    # 1. 清理历史回收引用
                    if item.get('reference_foreshadow_id') == foreshadow_id:
                        should_remove = True

                    # 2. 清理历史埋入记录,避免"手动同步分析伏笔"再次从 PlotAnalysis 重建已删除伏笔
                    if not should_remove and foreshadow.source_type == 'analysis':
                        item_type = item.get('type')
                        item_content = (item.get('content') or '').strip()
                        item_title = (item.get('title') or '').strip()
                        item_source_memory_id = None

                        if item_type == 'planted' and item_content and analysis.chapter_id == foreshadow.plant_chapter_id:
                            item_source_memory_id = generate_stable_foreshadow_id(analysis.chapter_id, item_content, item_type)

                            if (
                                foreshadow.source_memory_id
                                and item_source_memory_id == foreshadow.source_memory_id
                                or (
                                    item_title
                                    and foreshadow.title
                                    and item_title == foreshadow.title.strip()
                                    and content_snippet
                                    and content_snippet in item_content
                                )
                            ):
                                should_remove = True

                    if should_remove:
                        removed_count += 1
                        continue

                    filtered_foreshadows.append(item)

                if removed_count > 0:
                    analysis.foreshadows = filtered_foreshadows
                    analysis.foreshadows_planted = sum(1 for f in filtered_foreshadows if isinstance(f, dict) and f.get('type') == 'planted')
                    analysis.foreshadows_resolved = sum(1 for f in filtered_foreshadows if isinstance(f, dict) and f.get('type') == 'resolved')
                    cleaned_analysis_refs += removed_count
                    cleaned_analysis_rows += 1
                    logger.info(
                        f'🧹 已清理章节分析 {analysis.chapter_id[:8]} 中 {removed_count} 条已删除伏笔历史记录 '
                        f'(原数量: {original_count}, 现数量: {len(filtered_foreshadows)})'
                    )

            await db.delete(foreshadow)
            await db.commit()

            logger.info(
                f'✅ 删除伏笔成功: {foreshadow.title} '
                f'(关系记忆清理: {deleted_memory_rows}条, 向量记忆清理: {deleted_vector_memories}条, '
                f'历史分析引用清理: {cleaned_analysis_refs}条/{cleaned_analysis_rows}个分析)'
            )
            return True

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 删除伏笔失败: {str(e)}')
            raise

    async def mark_as_planted(self, db: AsyncSession, foreshadow_id: str, data: PlantForeshadowRequest) -> Foreshadow | None:
        """
        标记伏笔为已埋入

        Args:
            db: 数据库会话
            foreshadow_id: 伏笔ID
            data: 埋入信息

        Returns:
            更新后的伏笔对象
        """
        try:
            foreshadow = await self.get_foreshadow(db, foreshadow_id)
            if not foreshadow:
                return None

            foreshadow.status = 'planted'
            foreshadow.plant_chapter_id = data.chapter_id
            foreshadow.plant_chapter_number = data.chapter_number
            foreshadow.planted_at = datetime.now()

            if data.hint_text:
                foreshadow.hint_text = data.hint_text

            await db.commit()
            await db.refresh(foreshadow)

            logger.info(f'✅ 伏笔已标记为埋入: {foreshadow.title} (第{data.chapter_number}章)')
            return foreshadow

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 标记伏笔埋入失败: {str(e)}')
            raise

    async def mark_as_resolved(self, db: AsyncSession, foreshadow_id: str, data: ResolveForeshadowRequest) -> Foreshadow | None:
        """
        标记伏笔为已回收

        Args:
            db: 数据库会话
            foreshadow_id: 伏笔ID
            data: 回收信息

        Returns:
            更新后的伏笔对象
        """
        try:
            foreshadow = await self.get_foreshadow(db, foreshadow_id)
            if not foreshadow:
                return None

            if data.is_partial:
                foreshadow.status = 'partially_resolved'
            else:
                foreshadow.status = 'resolved'

            foreshadow.actual_resolve_chapter_id = data.chapter_id
            foreshadow.actual_resolve_chapter_number = data.chapter_number
            foreshadow.resolved_at = datetime.now()

            if data.resolution_text:
                foreshadow.resolution_text = data.resolution_text

            await db.commit()
            await db.refresh(foreshadow)

            logger.info(f'✅ 伏笔已标记为回收: {foreshadow.title} (第{data.chapter_number}章)')
            return foreshadow

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 标记伏笔回收失败: {str(e)}')
            raise

    async def mark_as_abandoned(self, db: AsyncSession, foreshadow_id: str, reason: str | None = None) -> Foreshadow | None:
        """标记伏笔为已废弃"""
        try:
            foreshadow = await self.get_foreshadow(db, foreshadow_id)
            if not foreshadow:
                return None

            foreshadow.status = 'abandoned'
            if reason:
                foreshadow.notes = f'{foreshadow.notes or ""}\n[废弃原因] {reason}'.strip()

            await db.commit()
            await db.refresh(foreshadow)

            logger.info(f'✅ 伏笔已标记为废弃: {foreshadow.title}')
            return foreshadow

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 标记伏笔废弃失败: {str(e)}')
            raise

    async def sync_from_analysis(self, db: AsyncSession, project_id: str, data: SyncFromAnalysisRequest) -> dict[str, Any]:
        """
        从章节分析结果同步伏笔(重构版)

        统一复用 auto_update_from_analysis 的核心逻辑,避免重复代码。
        本方法仅负责从 PlotAnalysis 表读取数据,然后委托处理。

        Args:
            db: 数据库会话
            project_id: 项目ID
            data: 同步请求数据

        Returns:
            同步结果
        """
        try:
            total_stats = {'synced_count': 0, 'skipped_count': 0, 'resolved_count': 0, 'new_foreshadows': [], 'skipped_reasons': []}

            # 获取分析结果
            query = select(PlotAnalysis).where(PlotAnalysis.project_id == project_id)
            if data.chapter_ids:
                query = query.where(PlotAnalysis.chapter_id.in_(data.chapter_ids))

            result = await db.execute(query)
            analyses = result.scalars().all()

            # 消除N+1:批量预查所有章节信息
            chapter_ids = [a.chapter_id for a in analyses if a.foreshadows]
            chapter_map: dict = {}
            if chapter_ids:
                chapters_result = await db.execute(select(Chapter).where(Chapter.id.in_(chapter_ids)))
                chapter_map = {ch.id: ch for ch in chapters_result.scalars().all()}

            for analysis in analyses:
                if not analysis.foreshadows:
                    continue

                # 消除N+1:从预查字典获取章节信息
                chapter = chapter_map.get(analysis.chapter_id)
                if not chapter:
                    continue

                # 委托给统一的处理方法
                chapter_stats = await self.auto_update_from_analysis(
                    db=db,
                    project_id=project_id,
                    chapter_id=chapter.id,
                    chapter_number=chapter.chapter_number,
                    analysis_foreshadows=analysis.foreshadows,
                )

                # 汇总统计
                total_stats['synced_count'] += chapter_stats.get('planted_count', 0) + chapter_stats.get('resolved_count', 0)
                total_stats['resolved_count'] += chapter_stats.get('resolved_count', 0)
                total_stats['skipped_count'] += chapter_stats.get('skipped_resolve_count', 0)

            logger.info(
                f'✅ 伏笔同步完成: 同步{total_stats["synced_count"]}个'
                f'(其中回收{total_stats["resolved_count"]}个), 跳过{total_stats["skipped_count"]}个'
            )

            return total_stats

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 同步伏笔失败: {str(e)}')
            raise

    async def get_pending_resolve_foreshadows(self, db: AsyncSession, project_id: str, current_chapter: int, lookahead: int = 5) -> list[Foreshadow]:
        """
        获取即将需要回收的伏笔

        Args:
            db: 数据库会话
            project_id: 项目ID
            current_chapter: 当前章节号
            lookahead: 向前看几章

        Returns:
            待回收伏笔列表
        """
        try:
            # 查询已埋入且计划在接下来几章回收的伏笔
            query = (
                select(Foreshadow)
                .where(
                    and_(
                        Foreshadow.project_id == project_id,
                        Foreshadow.status == 'planted',
                        Foreshadow.target_resolve_chapter_number.is_not(None),
                        Foreshadow.target_resolve_chapter_number <= current_chapter + lookahead,
                        Foreshadow.auto_remind.is_(True),
                    )
                )
                .order_by(Foreshadow.target_resolve_chapter_number)
            )

            result = await db.execute(query)
            return list(result.scalars().all())

        except Exception as e:
            logger.error(f'❌ 获取待回收伏笔失败: {str(e)}')
            return []

    async def get_overdue_foreshadows(self, db: AsyncSession, project_id: str, current_chapter: int) -> list[Foreshadow]:
        """
        获取超期未回收的伏笔

        Args:
            db: 数据库会话
            project_id: 项目ID
            current_chapter: 当前章节号

        Returns:
            超期伏笔列表
        """
        try:
            query = (
                select(Foreshadow)
                .where(
                    and_(
                        Foreshadow.project_id == project_id,
                        Foreshadow.status == 'planted',
                        Foreshadow.target_resolve_chapter_number.is_not(None),
                        Foreshadow.target_resolve_chapter_number < current_chapter,
                    )
                )
                .order_by(Foreshadow.target_resolve_chapter_number)
            )

            result = await db.execute(query)
            return list(result.scalars().all())

        except Exception as e:
            logger.error(f'❌ 获取超期伏笔失败: {str(e)}')
            return []

    async def get_must_resolve_foreshadows(self, db: AsyncSession, project_id: str, chapter_number: int) -> list[Foreshadow]:
        """
        获取本章必须回收的伏笔(target_resolve_chapter_number == chapter_number)

        这些伏笔是用户明确指定在本章回收的,必须在本章完成回收

        Args:
            db: 数据库会话
            project_id: 项目ID
            chapter_number: 当前章节号

        Returns:
            必须回收的伏笔列表
        """
        try:
            query = (
                select(Foreshadow)
                .where(
                    and_(
                        Foreshadow.project_id == project_id,
                        Foreshadow.status == 'planted',
                        Foreshadow.target_resolve_chapter_number == chapter_number,
                    )
                )
                .order_by(desc(Foreshadow.importance))
            )

            result = await db.execute(query)
            return list(result.scalars().all())

        except Exception as e:
            logger.error(f'❌ 获取本章必须回收伏笔失败: {str(e)}')
            return []

    async def get_foreshadows_to_plant(self, db: AsyncSession, project_id: str, chapter_number: int) -> list[Foreshadow]:
        """
        获取计划在本章埋入的伏笔

        Args:
            db: 数据库会话
            project_id: 项目ID
            chapter_number: 章节号

        Returns:
            待埋入伏笔列表
        """
        try:
            query = (
                select(Foreshadow)
                .where(and_(Foreshadow.project_id == project_id, Foreshadow.status == 'pending', Foreshadow.plant_chapter_number == chapter_number))
                .order_by(desc(Foreshadow.importance))
            )

            result = await db.execute(query)
            return list(result.scalars().all())

        except Exception as e:
            logger.error(f'❌ 获取待埋入伏笔失败: {str(e)}')
            return []

    async def build_chapter_context(
        self, db: AsyncSession, project_id: str, chapter_number: int, include_pending: bool = True, include_overdue: bool = True, lookahead: int = 5
    ) -> dict[str, Any]:
        """
        构建章节生成的伏笔上下文(智能分层提醒策略)

        核心策略:
        1. 本章必须回收的伏笔 → 明确要求回收
        2. 超期伏笔 → 强调需要尽快回收
        3. 即将回收的伏笔 → 仅作为背景信息,明确禁止提前回收
        4. 远期伏笔 → 不发送,防止干扰

        Args:
            db: 数据库会话
            project_id: 项目ID
            chapter_number: 章节号
            include_pending: 包含待埋入伏笔
            include_overdue: 包含超期伏笔
            lookahead: 向前看几章(用于背景提醒,非强制回收)

        Returns:
            伏笔上下文信息
        """
        try:
            lines = []
            to_plant = []
            must_resolve = []  # 本章必须回收
            overdue = []  # 超期待回收
            upcoming = []  # 即将回收(仅参考)

            # 1. 获取本章必须回收的伏笔(target_resolve_chapter_number == chapter_number)
            must_resolve = await self.get_must_resolve_foreshadows(db, project_id, chapter_number)
            if must_resolve:
                lines.append('【🎯 本章必须回收的伏笔 - 请务必在本章完成回收】')
                for f in must_resolve:
                    lines.append(f'- ID:{f.id[:8]} | {f.title}')
                    lines.append(f'  埋入章节:第{f.plant_chapter_number}章')
                    lines.append(f'  伏笔内容:{f.content[:100]}{"..." if len(f.content) > 100 else ""}')
                    if f.resolution_notes:
                        lines.append(f'  回收提示:{f.resolution_notes}')
                    lines.append('')

            # 2. 超期伏笔(已过目标回收章节但未回收)
            if include_overdue:
                overdue = await self.get_overdue_foreshadows(db, project_id, chapter_number)
                if overdue:
                    lines.append('【⚠️ 超期待回收伏笔 - 请尽快回收】')
                    for f in overdue[:3]:
                        overdue_chapters = chapter_number - (f.target_resolve_chapter_number or 0)
                        lines.append(f'- ID:{f.id[:8]} | {f.title} [已超期{overdue_chapters}章]')
                        lines.append(f'  埋入章节:第{f.plant_chapter_number}章,原计划第{f.target_resolve_chapter_number}章回收')
                        lines.append(f'  伏笔内容:{f.content[:80]}...')
                    lines.append('')

            # 3. 即将需要回收的伏笔(仅作为背景参考,明确禁止提前回收)
            upcoming_raw = await self.get_pending_resolve_foreshadows(db, project_id, chapter_number, lookahead)
            # 过滤:排除本章必须回收的和超期的,只保留未来章节的
            upcoming = [f for f in upcoming_raw if (f.target_resolve_chapter_number or 0) > chapter_number]

            if upcoming:
                lines.append('【📋 近期待回收伏笔(仅供参考,请勿在本章回收)】')
                lines.append('⚠️ 以下伏笔尚未到回收时机,本章请勿提前回收,仅作为剧情背景了解')
                for f in upcoming[:5]:
                    remaining = (f.target_resolve_chapter_number or 0) - chapter_number
                    lines.append(f'- {f.title}(计划第{f.target_resolve_chapter_number}章回收,还有{remaining}章)')
                lines.append('')

            # 4. 本章待埋入伏笔
            if include_pending:
                to_plant = await self.get_foreshadows_to_plant(db, project_id, chapter_number)
                if to_plant:
                    lines.append('【✨ 本章计划埋入伏笔】')
                    for f in to_plant:
                        content_preview = f.content[:80] if len(f.content) > 80 else f.content
                        lines.append(f'- {f.title}')
                        lines.append(f'  伏笔内容:{content_preview}')
                        if f.hint_text:
                            lines.append(f'  埋入提示:{f.hint_text}')
                    lines.append('')

            context_text = '\n'.join(lines) if lines else ''

            return {
                'chapter_number': chapter_number,
                'context_text': context_text,
                'pending_plant': [f.to_dict() for f in to_plant],
                'must_resolve': [f.to_dict() for f in must_resolve],
                'pending_resolve': [f.to_dict() for f in upcoming],
                'overdue': [f.to_dict() for f in overdue],
                'recently_planted': [],  # 可扩展
            }

        except Exception as e:
            logger.error(f'❌ 构建伏笔上下文失败: {str(e)}')
            return {
                'chapter_number': chapter_number,
                'context_text': '',
                'pending_plant': [],
                'must_resolve': [],
                'pending_resolve': [],
                'overdue': [],
                'recently_planted': [],
            }

    async def get_stats(self, db: AsyncSession, project_id: str, current_chapter: int | None = None) -> dict[str, int]:
        """
        获取伏笔统计

        Args:
            db: 数据库会话
            project_id: 项目ID
            current_chapter: 当前章节号(用于计算超期)

        Returns:
            统计信息字典
        """
        try:
            # 各状态统计
            stats_query = (
                select(Foreshadow.status, func.count(Foreshadow.id).label('count'))
                .where(Foreshadow.project_id == project_id)
                .group_by(Foreshadow.status)
            )

            result = await db.execute(stats_query)
            status_counts = {row.status: row.count for row in result}

            # 总数
            total = sum(status_counts.values())

            # 长线伏笔数量
            long_term_query = select(func.count(Foreshadow.id)).where(and_(Foreshadow.project_id == project_id, Foreshadow.is_long_term.is_(True)))
            long_term_result = await db.execute(long_term_query)
            long_term_count = long_term_result.scalar() or 0

            # 超期数量
            overdue_count = 0
            if current_chapter:
                overdue = await self.get_overdue_foreshadows(db, project_id, current_chapter)
                overdue_count = len(overdue)

            return {
                'total': total,
                'pending': status_counts.get('pending', 0),
                'planted': status_counts.get('planted', 0),
                'resolved': status_counts.get('resolved', 0),
                'partially_resolved': status_counts.get('partially_resolved', 0),
                'abandoned': status_counts.get('abandoned', 0),
                'long_term_count': long_term_count,
                'overdue_count': overdue_count,
            }

        except Exception as e:
            logger.error(f'❌ 获取伏笔统计失败: {str(e)}')
            return {
                'total': 0,
                'pending': 0,
                'planted': 0,
                'resolved': 0,
                'partially_resolved': 0,
                'abandoned': 0,
                'long_term_count': 0,
                'overdue_count': 0,
            }

    async def get_planted_foreshadows_for_analysis(
        self, db: AsyncSession, project_id: str, current_chapter_number: int | None = None
    ) -> list[dict[str, Any]]:
        """
        获取用于分析时注入的已埋入伏笔列表(智能过滤版)

        策略:
        1. 只返回 status='planted' 的伏笔
        2. 如果指定了当前章节号,会标记哪些伏笔应该在本章回收
        3. 区分"可回收"和"不可回收"伏笔,帮助AI正确识别

        Args:
            db: 数据库会话
            project_id: 项目ID
            current_chapter_number: 当前章节号(可选,用于智能标记)

        Returns:
            伏笔列表(带回收标记)
        """
        try:
            query = (
                select(Foreshadow)
                .where(and_(Foreshadow.project_id == project_id, Foreshadow.status == 'planted'))
                .order_by(Foreshadow.plant_chapter_number)
            )

            result = await db.execute(query)
            foreshadows = result.scalars().all()

            formatted_list = []
            for f in foreshadows:
                item = {
                    'id': f.id,
                    'title': f.title,
                    'content': f.content,
                    'hint_text': f.hint_text,
                    'plant_chapter_number': f.plant_chapter_number,
                    'target_resolve_chapter_number': f.target_resolve_chapter_number,
                    'category': f.category,
                    'related_characters': f.related_characters or [],
                    'is_long_term': f.is_long_term,
                }

                # 智能标记回收状态
                if current_chapter_number and f.target_resolve_chapter_number:
                    if f.target_resolve_chapter_number == current_chapter_number:
                        item['resolve_status'] = 'must_resolve_now'  # 本章必须回收
                        item['resolve_hint'] = '本章必须回收此伏笔'
                    elif f.target_resolve_chapter_number < current_chapter_number:
                        item['resolve_status'] = 'overdue'  # 已超期
                        item['resolve_hint'] = f'已超期{current_chapter_number - f.target_resolve_chapter_number}章,应尽快回收'
                    else:
                        item['resolve_status'] = 'not_yet'  # 尚未到期
                        item['resolve_hint'] = f'计划第{f.target_resolve_chapter_number}章回收,请勿提前回收'
                else:
                    item['resolve_status'] = 'no_plan'  # 无明确计划
                    item['resolve_hint'] = '无明确回收计划,根据剧情自然回收'

                formatted_list.append(item)

            return formatted_list

        except Exception as e:
            logger.error(f'❌ 获取已埋入伏笔失败: {str(e)}')
            return []

    async def delete_chapter_foreshadows(
        self, db: AsyncSession, project_id: str, chapter_id: str, only_analysis_source: bool = True
    ) -> dict[str, Any]:
        """
        删除与指定章节相关的伏笔

        当章节内容被清空或重新生成时调用,清理残留数据

        Args:
            db: 数据库会话
            project_id: 项目ID
            chapter_id: 章节ID
            only_analysis_source: 是否只删除来源为 analysis 的伏笔(默认True)
                                  如果为False,则删除所有与该章节相关的伏笔

        Returns:
            删除统计信息
        """
        try:
            # 1. 先通过 PlotAnalysis 查找该章节的分析ID
            # 这是关键:sync_from_analysis 创建的伏笔使用 source_analysis_id 关联
            analysis_query = select(PlotAnalysis.id).where(PlotAnalysis.chapter_id == chapter_id)
            analysis_result = await db.execute(analysis_query)
            analysis_ids = [row[0] for row in analysis_result.fetchall()]

            logger.debug(f'🔍 找到章节 {chapter_id[:8]} 的分析ID: {len(analysis_ids)} 个')

            # 2. 构建查询条件:查找与该章节相关的伏笔
            # 匹配方式:
            # 1. 埋入章节是该章节 (plant_chapter_id)
            # 2. 回收章节是该章节 (actual_resolve_chapter_id)
            # 3. 来源分析ID对应该章节的分析 (source_analysis_id)
            or_conditions = [
                Foreshadow.plant_chapter_id == chapter_id,
                Foreshadow.actual_resolve_chapter_id == chapter_id,
            ]

            # 如果找到了分析ID,添加 source_analysis_id 匹配条件
            if analysis_ids:
                or_conditions.append(Foreshadow.source_analysis_id.in_(analysis_ids))

            conditions = [Foreshadow.project_id == project_id, or_(*or_conditions)]

            # 如果只删除分析来源的伏笔
            if only_analysis_source:
                conditions.append(Foreshadow.source_type == 'analysis')

            # 查询要删除的伏笔
            query = select(Foreshadow).where(and_(*conditions))
            result = await db.execute(query)
            foreshadows_to_delete = result.scalars().all()

            deleted_count = len(foreshadows_to_delete)
            deleted_ids = [f.id for f in foreshadows_to_delete]
            deleted_titles = [f.title for f in foreshadows_to_delete]

            # 执行删除
            for foreshadow in foreshadows_to_delete:
                await db.delete(foreshadow)

            await db.commit()

            if deleted_count > 0:
                logger.info(f'🗑️ 已删除章节 {chapter_id[:8]} 相关的 {deleted_count} 个伏笔')
                for title in deleted_titles[:5]:  # 只打印前5个
                    logger.debug(f'  - {title}')
                if deleted_count > 5:
                    logger.debug(f'  ... 还有 {deleted_count - 5} 个')

            return {'deleted_count': deleted_count, 'deleted_ids': deleted_ids, 'deleted_titles': deleted_titles}

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 删除章节伏笔失败: {str(e)}')
            raise

    async def clean_chapter_analysis_foreshadows(self, db: AsyncSession, project_id: str, chapter_id: str) -> dict[str, Any]:
        """
        清理章节分析产生的伏笔(用于重新分析前的清理)

        两步操作:
        1. 删除 source_type='analysis' 且 plant_chapter_id == chapter_id 的伏笔
        2. 回退在本章被回收的伏笔(将其从 resolved 恢复为 planted)

        保留手动创建的伏笔

        Args:
            db: 数据库会话
            project_id: 项目ID
            chapter_id: 章节ID

        Returns:
            清理统计信息
        """
        try:
            # 步骤1: 删除在本章埋入的分析伏笔
            query = select(Foreshadow).where(
                and_(Foreshadow.project_id == project_id, Foreshadow.source_type == 'analysis', Foreshadow.plant_chapter_id == chapter_id)
            )

            result = await db.execute(query)
            foreshadows_to_clean = result.scalars().all()

            cleaned_count = len(foreshadows_to_clean)
            cleaned_ids = [f.id for f in foreshadows_to_clean]

            for foreshadow in foreshadows_to_clean:
                await db.delete(foreshadow)

            # 步骤2: 回退在本章被回收的伏笔(恢复为 planted 状态)
            reverted_count = await self._revert_chapter_resolutions(db, project_id, chapter_id)

            await db.commit()

            if cleaned_count > 0 or reverted_count > 0:
                logger.info(f'🧹 已清理章节 {chapter_id[:8]}: 删除{cleaned_count}个分析伏笔, 回退{reverted_count}个回收状态')

            return {'cleaned_count': cleaned_count, 'cleaned_ids': cleaned_ids, 'reverted_count': reverted_count}

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 清理章节分析伏笔失败: {str(e)}')
            raise

    async def _revert_chapter_resolutions(self, db: AsyncSession, project_id: str, chapter_id: str) -> int:
        """
        回退在指定章节中被回收的伏笔

        将 actual_resolve_chapter_id == chapter_id 且 status 为 resolved/partially_resolved 的伏笔
        恢复为 planted 状态,以便重新分析时可以重新匹配回收

        Args:
            db: 数据库会话
            project_id: 项目ID
            chapter_id: 章节ID

        Returns:
            回退的伏笔数量
        """
        try:
            update_query = (
                update(Foreshadow)
                .where(
                    and_(
                        Foreshadow.project_id == project_id,
                        Foreshadow.actual_resolve_chapter_id == chapter_id,
                        Foreshadow.status.in_(['resolved', 'partially_resolved']),
                    )
                )
                .values(status='planted', actual_resolve_chapter_id=None, actual_resolve_chapter_number=None, resolved_at=None, resolution_text=None)
            )
            result = await db.execute(update_query)
            reverted_count = result.rowcount

            if reverted_count > 0:
                logger.info(f'↩️ 回退了 {reverted_count} 个在章节 {chapter_id[:8]} 中被回收的伏笔')

            return reverted_count

        except Exception as e:
            logger.error(f'❌ 回退章节回收失败: {str(e)}')
            return 0

    async def clear_project_foreshadows_for_reset(self, db: AsyncSession, project_id: str) -> dict[str, int]:
        """
        全新生成时清理项目伏笔

        1. 删除所有 source_type='analysis' 的伏笔
        2. 重置所有 source_type='manual' 的伏笔为 pending 状态

        Args:
            db: 数据库会话
            project_id: 项目ID

        Returns:
            清理统计
        """
        try:
            # 1. 删除分析产生的伏笔
            delete_query = delete(Foreshadow).where(and_(Foreshadow.project_id == project_id, Foreshadow.source_type == 'analysis'))
            delete_result = await db.execute(delete_query)
            deleted_count = delete_result.rowcount

            # 2. 重置手动创建的伏笔
            # 将 planted/resolved/partially_resolved 状态重置为 pending
            # 清空章节关联信息
            update_query = (
                update(Foreshadow)
                .where(
                    and_(
                        Foreshadow.project_id == project_id,
                        Foreshadow.source_type == 'manual',
                        Foreshadow.status.in_(['planted', 'resolved', 'partially_resolved']),
                    )
                )
                .values(
                    status='pending',
                    plant_chapter_id=None,
                    plant_chapter_number=None,
                    actual_resolve_chapter_id=None,
                    actual_resolve_chapter_number=None,
                    planted_at=None,
                    resolved_at=None,
                    target_resolve_chapter_id=None,
                    target_resolve_chapter_number=None,
                )
            )
            update_result = await db.execute(update_query)
            reset_count = update_result.rowcount

            await db.commit()

            logger.info(f'🧹 项目 {project_id} 伏笔清理完成: 删除 {deleted_count} 个分析伏笔, 重置 {reset_count} 个手动伏笔')

            return {'deleted_count': deleted_count, 'reset_count': reset_count}

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 清理项目伏笔失败: {str(e)}')
            raise


foreshadow_service = ForeshadowService()
