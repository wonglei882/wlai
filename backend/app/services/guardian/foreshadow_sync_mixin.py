"""伏笔自动同步 Mixin — 从 foreshadow_service.py 拆分。

包含 auto_update_from_analysis / auto_plant_pending_foreshadows /
_match_foreshadow_by_content / _calculate_word_overlap。
"""

import re
import uuid
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime

from app.core import json_utils as json
from app.models.foreshadow import Foreshadow
from app.services._foreshadow_helpers import generate_stable_foreshadow_id
import logging

logger = logging.getLogger(__name__)


class ForeshadowSyncMixin:
    """伏笔自动同步逻辑（从 foreshadow_service.py 拆分）。"""

    async def auto_update_from_analysis(
        self, db: AsyncSession, project_id: str, chapter_id: str, chapter_number: int, analysis_foreshadows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        根据章节分析结果自动更新伏笔状态

        功能:
        1. 自动标记新埋入的伏笔为 planted
        2. 根据 reference_foreshadow_id 自动回收已有伏笔
        3. 如果没有 reference_foreshadow_id,使用内容匹配备用机制
        4. 创建新发现的伏笔记录

        Args:
            db: 数据库会话
            project_id: 项目ID
            chapter_id: 章节ID
            chapter_number: 章节号
            analysis_foreshadows: 分析结果中的伏笔列表

        Returns:
            更新统计
        """
        try:
            stats = {
                'planted_count': 0,  # 新埋入的伏笔
                'resolved_count': 0,  # 回收的伏笔
                'created_count': 0,  # 新创建的伏笔记录
                'updated_ids': [],  # 更新的伏笔ID
                'created_ids': [],  # 创建的伏笔ID
                'matched_by_content': 0,  # 通过内容匹配回收的数量
                'errors': [],  # 错误信息
            }

            # 预先获取所有已埋入的伏笔,用于内容匹配
            planted_foreshadows = await self.get_planted_foreshadows_for_analysis(db, project_id)

            # 消除N+1:批量预加载所有伏笔数据(通过 reference_id 和 source_memory_id/chapter_id/title)
            # 先提取所有已知 ID
            ref_ids = []
            for fs_data in analysis_foreshadows:
                rid = fs_data.get('reference_foreshadow_id')
                if rid:
                    import re

                    rid_s = str(rid).strip()
                    # 宽松匹配：允许 canonical UUID、短 hex、{前缀}-{hex} 形式
                    m = re.search(
                        r'[0-9a-f]{8,}(?:-[0-9a-f]{4,})*',
                        rid_s,
                        re.I,
                    )
                    if m:
                        ref_ids.append(rid_s)
            # 提取 planted 类型的 source_memory_id(按本章 chapter_id)
            fs_keys = []  # list of (source_memory_id, chapter_id, fs_title, fs_data)
            for fs_data in analysis_foreshadows:
                if fs_data.get('type') == 'planted':
                    fs_content = fs_data.get('content', '') or ''
                    sm_id = generate_stable_foreshadow_id(chapter_id, fs_content, 'planted')
                    fs_title = fs_data.get('title') or (fs_content[:50] + ('...' if len(fs_content) > 50 else ''))
                    fs_keys.append((sm_id, chapter_id, fs_title, fs_data))

            # 批量查询所有 reference_id
            fs_by_ref_id: dict = {}
            if ref_ids:
                ref_result = await db.execute(select(Foreshadow).where(Foreshadow.id.in_(ref_ids)))
                fs_by_ref_id = {f.id: f for f in ref_result.scalars().all()}

            # 批量查询所有 planted 伏笔(通过 source_memory_id)
            sm_ids = [k[0] for k in fs_keys]
            fs_by_sm: dict = {}
            if sm_ids:
                sm_result = await db.execute(
                    select(Foreshadow).where(
                        Foreshadow.project_id == project_id,
                        Foreshadow.source_memory_id.in_(sm_ids),
                        Foreshadow.plant_chapter_id == chapter_id,
                        Foreshadow.source_type == 'analysis',
                    )
                )
                fs_by_sm = {f.source_memory_id: f for f in sm_result.scalars().all()}

            # 批量查询所有 planted 伏笔(通过 title+chapter_id 备用)
            fs_titles = [(k[2], k[1]) for k in fs_keys]
            fs_by_title: dict = {}
            if fs_titles:
                title_result = await db.execute(
                    select(Foreshadow).where(
                        Foreshadow.project_id == project_id, Foreshadow.plant_chapter_id == chapter_id, Foreshadow.source_type == 'analysis'
                    )
                )
                fs_by_title = {f.title: f for f in title_result.scalars().all()}

            # 每章最多创建的新伏笔数量
            MAX_NEW_FORESHADOWS_PER_CHAPTER = 5
            new_foreshadow_count = 0

            for fs_data in analysis_foreshadows:
                try:
                    fs_type = fs_data.get('type', 'planted')
                    reference_id = fs_data.get('reference_foreshadow_id')

                    if fs_type == 'resolved':
                        existing = None
                        matched_by_content = False

                        # 策略1: 优先使用 reference_id 精确匹配（消除N+1：从预加载数据获取）
                        if reference_id:
                            import re

                            rid_s = str(reference_id).strip()
                            id_match = re.search(
                                r'[0-9a-f]{8,}(?:-[0-9a-f]{4,})*',
                                rid_s,
                                re.I,
                            )
                            if id_match:
                                rid = rid_s  # 直接使用调用方传入值，避免短 ID 被截断
                                existing = fs_by_ref_id.get(rid)
                                if existing and existing.project_id == project_id:
                                    logger.info(f'🎯 通过ID精确匹配伏笔: {existing.title}')
                                else:
                                    existing = None
                                    logger.warning(f'⚠️ 伏笔ID不存在或不属于该项目，跳过本次回收同步: {rid}')
                                    stats['skipped_resolve_count'] = stats.get('skipped_resolve_count', 0) + 1
                                    stats['errors'].append(f'reference_foreshadow_id 无效或已删除: {rid}')
                                    continue
                            else:
                                continue

                        # 策略2: 内容匹配备用机制（仅在 analysis 未提供 reference_id 时启用）
                        if not reference_id and not existing and planted_foreshadows:
                            matched = self._match_foreshadow_by_content(fs_data, planted_foreshadows)
                            if matched:
                                matched_by_content = True
                                logger.info(f'🔍 通过内容匹配找到伏笔: {matched.get("title")}')
                                # 从预加载数据中查找
                                matched_id = matched.get('id')
                                if matched_id:
                                    for f in list(fs_by_ref_id.values()) + list(fs_by_sm.values()):
                                        if f.id == matched_id:
                                            existing = f
                                            break

                        # 检查伏笔是否已被回收(防止重复回收)
                        if existing:
                            if existing.status == 'resolved' and existing.actual_resolve_chapter_number == chapter_number:
                                logger.info(f'i️ 伏笔已在本章回收过,跳过: {existing.title}')
                                continue
                            elif existing.status == 'resolved':
                                logger.warning(f'⚠️ 伏笔已在第{existing.actual_resolve_chapter_number}章回收,跳过: {existing.title}')
                                continue

                        # 执行回收
                        if existing and existing.status == 'planted':
                            # 更新为已回收状态
                            existing.status = 'resolved'
                            existing.actual_resolve_chapter_id = chapter_id
                            existing.actual_resolve_chapter_number = chapter_number
                            existing.resolved_at = datetime.now()

                            # 更新回收文本
                            if fs_data.get('content'):
                                existing.resolution_text = fs_data.get('content')

                            await db.flush()
                            await db.refresh(existing)

                            stats['resolved_count'] += 1
                            stats['updated_ids'].append(existing.id)
                            if matched_by_content:
                                stats['matched_by_content'] += 1
                            logger.info(f'✅ 自动回收伏笔: {existing.title} (ID: {existing.id}, status: {existing.status})')

                            # 从待匹配列表中移除已回收的伏笔
                            planted_foreshadows = [f for f in planted_foreshadows if f['id'] != existing.id]
                        elif existing:
                            logger.warning(f'⚠️ 伏笔状态不是planted,跳过回收: {existing.title} (status: {existing.status})')
                        else:
                            # 找不到匹配的已埋入伏笔,跳过(不创建新记录!)
                            # 核心原则:只有"埋入"操作会创建伏笔记录,"回收"只是更新已有记录
                            # 如果没有埋入的伏笔,就不可能存在回收
                            fs_title = fs_data.get('title', fs_data.get('content', '')[:30])
                            logger.warning(f'⚠️ 未找到匹配的已埋入伏笔,跳过回收(不创建新记录): {fs_title}')
                            logger.warning('   提示:AI可能误识别了回收伏笔,或者 reference_foreshadow_id 未正确填写')
                            stats['skipped_resolve_count'] = stats.get('skipped_resolve_count', 0) + 1
                            continue

                    elif fs_type == 'planted':
                        fs_content = fs_data.get('content', '')
                        if not fs_content:
                            logger.warning('⚠️ 伏笔内容为空,跳过')
                            continue

                        fs_title = fs_data.get('title', '')
                        if not fs_title:
                            fs_title = fs_content[:50] + ('...' if len(fs_content) > 50 else '')

                        # 使用稳定的唯一标识符(基于 chapter_id + content_hash)
                        source_memory_id = generate_stable_foreshadow_id(chapter_id, fs_content, fs_type)

                        # 消除N+1：从预加载数据中查找
                        existing_fs = fs_by_sm.get(source_memory_id)
                        if not existing_fs:
                            # 备用：按标题+章节号匹配（兼容旧数据）
                            existing_fs = fs_by_title.get(fs_title)

                        if existing_fs:
                            # 更新已存在的伏笔,避免重复创建
                            existing_fs.title = fs_title
                            existing_fs.content = fs_content
                            existing_fs.strength = fs_data.get('strength', existing_fs.strength)
                            existing_fs.subtlety = fs_data.get('subtlety', existing_fs.subtlety)
                            existing_fs.hint_text = fs_data.get('keyword', existing_fs.hint_text)
                            existing_fs.category = fs_data.get('category', existing_fs.category)
                            existing_fs.is_long_term = fs_data.get('is_long_term', existing_fs.is_long_term)
                            existing_fs.related_characters = fs_data.get('related_characters', existing_fs.related_characters)
                            if fs_data.get('estimated_resolve_chapter'):
                                existing_fs.target_resolve_chapter_number = fs_data.get('estimated_resolve_chapter')
                            # 更新为稳定的source_memory_id
                            existing_fs.source_memory_id = source_memory_id
                            await db.flush()
                            stats['updated_ids'].append(existing_fs.id)
                            logger.info(f'📝 更新已存在伏笔(避免重复): {fs_title} (ID: {existing_fs.id})')
                        else:
                            # 创建新伏笔
                            # 检查每章新伏笔数量上限
                            if new_foreshadow_count >= MAX_NEW_FORESHADOWS_PER_CHAPTER:
                                logger.info(f'🚫 已达每章新伏笔上限({MAX_NEW_FORESHADOWS_PER_CHAPTER}个),跳过: {fs_title}')
                                continue

                            # 不再为 estimated_resolve_chapter 设置默认值,避免误报"超期"
                            estimated_resolve = fs_data.get('estimated_resolve_chapter')
                            if estimated_resolve is None:
                                logger.info('i️ AI未填写estimated_resolve_chapter,不设默认值,标记为无明确回收计划')

                            new_foreshadow = Foreshadow(
                                id=str(uuid.uuid4()),
                                project_id=project_id,
                                title=fs_title,
                                content=fs_content,
                                hint_text=fs_data.get('keyword'),
                                source_type='analysis',
                                source_memory_id=source_memory_id,  # 使用稳定的唯一标识
                                plant_chapter_id=chapter_id,
                                plant_chapter_number=chapter_number,
                                planted_at=datetime.now(),
                                target_resolve_chapter_number=estimated_resolve,
                                status='planted',
                                is_long_term=fs_data.get('is_long_term', False),
                                importance=min(fs_data.get('strength', 5) / 10.0, 1.0),
                                strength=fs_data.get('strength', 5),
                                subtlety=fs_data.get('subtlety', 5),
                                category=fs_data.get('category'),
                                related_characters=fs_data.get('related_characters'),
                                auto_remind=True,
                                remind_before_chapters=5,
                                include_in_context=True,
                            )

                            db.add(new_foreshadow)
                            await db.flush()

                            new_foreshadow_count += 1
                            stats['planted_count'] += 1
                            stats['created_count'] += 1
                            stats['created_ids'].append(new_foreshadow.id)
                            logger.info(
                                f'✅ 自动创建伏笔: {fs_title} (ID: {new_foreshadow.id}) [{new_foreshadow_count}/{MAX_NEW_FORESHADOWS_PER_CHAPTER}]'
                            )

                except Exception as item_error:
                    error_msg = f'处理伏笔时出错: {str(item_error)}'
                    stats['errors'].append(error_msg)
                    logger.error(f'❌ {error_msg}')

            await db.commit()

            # 兜底:对"计划在本章回收"但AI没识别到的伏笔,自动回收
            if stats['resolved_count'] == 0:
                try:
                    must_resolve = await db.execute(
                        select(Foreshadow).where(
                            and_(
                                Foreshadow.project_id == project_id,
                                Foreshadow.status == 'planted',
                                Foreshadow.target_resolve_chapter_number < chapter_number,
                            )
                        )
                    )
                    missed = must_resolve.scalars().all()
                    for fs in missed:
                        fs.status = 'resolved'
                        fs.actual_resolve_chapter_id = chapter_id
                        fs.actual_resolve_chapter_number = chapter_number
                        fs.resolved_at = datetime.now()
                        fs.resolution_text = '[自动回收] AI分析未识别到回收事件,按计划章节自动标记'
                        stats['resolved_count'] += 1
                        stats['updated_ids'].append(fs.id)
                        logger.info(f'🔄 兜底自动回收伏笔: {fs.title} (计划第{chapter_number}章回收,AI未识别)')
                    if missed:
                        await db.commit()
                        logger.info(f'✅ 兜底回收完成: 自动回收{len(missed)}个伏笔')
                except Exception as fallback_err:
                    logger.warning(f'⚠️ 兜底回收失败: {fallback_err}')

            logger.info(f'📊 伏笔自动更新完成: 埋入{stats["planted_count"]}个, 回收{stats["resolved_count"]}个, 创建{stats["created_count"]}个')
            return stats

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 自动更新伏笔失败: {str(e)}')
            raise

    async def auto_plant_pending_foreshadows(
        self, db: AsyncSession, project_id: str, chapter_id: str, chapter_number: int, chapter_content: str
    ) -> dict[str, Any]:
        """
        自动将计划在本章埋入的伏笔标记为已埋入

        检查 pending 状态且 plant_chapter_number == chapter_number 的伏笔,
        如果章节内容中包含相关关键词,则自动标记为 planted

        Args:
            db: 数据库会话
            project_id: 项目ID
            chapter_id: 章节ID
            chapter_number: 章节号
            chapter_content: 章节内容

        Returns:
            更新统计
        """
        try:
            stats = {'checked_count': 0, 'planted_count': 0, 'planted_ids': []}

            # 获取计划在本章埋入的伏笔
            pending_foreshadows = await self.get_foreshadows_to_plant(db, project_id, chapter_number)

            stats['checked_count'] = len(pending_foreshadows)

            for fs in pending_foreshadows:
                # 通过章节内容关键词匹配判断伏笔是否真正被埋入
                should_plant = False
                if chapter_content and len(chapter_content) > 100:
                    _hits = []
                    _kc = chapter_content.lower()
                    for _kw in re.split(r'[\u3001\uff0c\u3002\u3001\uff1b\uff1a,.!?\\s]+', fs.title):
                        _kl = _kw.strip().lower()
                        if len(_kl) >= 4 and _kl in _kc:
                            _hits.append(f'title:{_kl}')
                    if fs.hint_text:
                        _ht = fs.hint_text.strip().lower()
                        if len(_ht) >= 6 and _ht in _kc:
                            _hits.append(f'hint:{_ht[:30]}')
                    if fs.content:
                        _ct = fs.content[:50].strip().lower()
                        if len(_ct) >= 6 and _ct in _kc:
                            _hits.append(f'content:{_ct[:30]}')
                    if fs.related_characters:
                        _rels = (
                            fs.related_characters
                            if isinstance(fs.related_characters, list)
                            else (json.loads(fs.related_characters) if isinstance(fs.related_characters, str) else [])
                        )
                        for _rc in _rels:
                            if isinstance(_rc, str) and len(_rc) >= 2 and _rc.lower() in _kc:
                                _hits.append(f'char:{_rc}')
                    # 多轮匹配策略(P0-2增强)
                    # 第1轮:关键词粗筛(快速排除不相关伏笔)
                    _strong_hits = [h for h in _hits if h.startswith('title:') or h.startswith('content:')]
                    keyword_match = len(_hits) >= 2 or (len(_strong_hits) >= 1 and len(_hits) >= 1)

                    # 第2轮:语义相似度(关键词匹配不通过但可能有语义关联)
                    _semantic_score = 0.0
                    if not keyword_match and chapter_content and len(chapter_content) > 200:
                        try:
                            _trigger = (fs.content or fs.title or '')[:200].lower()
                            _sampling = chapter_content[:3000].lower()
                            # 简单共享词袋相似度(无sentence-transformers时的轻量替代)
                            _trigger_words = set(w for w in _trigger.split() if len(w) >= 4)
                            _content_words = set(w for w in _sampling.split() if len(w) >= 4)
                            if _trigger_words and _content_words:
                                _intersection = _trigger_words & _content_words
                                _semantic_score = len(_intersection) / max(len(_trigger_words), 1)
                                if _semantic_score >= 0.3:
                                    _hits.append(f'semantic:{_semantic_score:.2f}')
                        except Exception as e:
                            logger.warning(f'[foreshadow_service] auto_plant_pending_foreshadows 失败: {e}')

                    should_plant = keyword_match or _semantic_score >= 0.3

                if should_plant:
                    fs.status = 'planted'
                    fs.plant_chapter_id = chapter_id
                    fs.planted_at = datetime.now()
                    await db.flush()

                    stats['planted_count'] += 1
                    stats['planted_ids'].append(fs.id)
                    logger.info(f'✅ 自动标记伏笔已埋入: {fs.title} (第{chapter_number}章, 命中{len(_hits)}个关键词)')
                else:
                    logger.info(f'⏸️ 伏笔『{fs.title}』计划在第{chapter_number}章埋入，但章节内容中未检测到关键词，暂不标记')
            await db.commit()

            if stats['planted_count'] > 0:
                logger.info(f'📊 自动埋入伏笔: 检查{stats["checked_count"]}个, 埋入{stats["planted_count"]}个')

            return stats

        except Exception as e:
            await db.rollback()
            logger.error(f'❌ 自动埋入伏笔失败: {str(e)}')
            return {'checked_count': 0, 'planted_count': 0, 'planted_ids': [], 'error': str(e)}

    def _match_foreshadow_by_content(
        self, resolved_fs_data: dict[str, Any], planted_foreshadows: list[dict[str, Any]], min_similarity: float = 0.5
    ) -> dict[str, Any] | None:
        """
        通过内容相似度匹配伏笔(备用机制)

        匹配策略(按优先级):
        1. 标题完全匹配(权重最高)
        2. 标题部分匹配(包含关系)
        3. 标题关键词匹配(去除"回收"等后缀)
        4. 关键词匹配
        5. 内容关键词匹配
        6. 相关角色匹配 + 分类匹配

        Args:
            resolved_fs_data: 分析结果中的回收伏笔数据
            planted_foreshadows: 已埋入的伏笔列表
            min_similarity: 最低相似度阈值

        Returns:
            最匹配的伏笔对象或None
        """
        if not planted_foreshadows:
            return None

        resolved_title = resolved_fs_data.get('title', '').strip()
        resolved_content = resolved_fs_data.get('content', '').strip()
        resolved_keyword = resolved_fs_data.get('keyword', '').strip()
        resolved_category = resolved_fs_data.get('category')
        resolved_characters = set(resolved_fs_data.get('related_characters', []))
        reference_chapter = resolved_fs_data.get('reference_chapter')

        # 处理标题后缀(兜底机制)
        resolved_title_clean = resolved_title
        for suffix in ['回收', '揭示', '解答', '兑现']:
            if resolved_title.endswith(suffix):
                resolved_title_clean = resolved_title[: -len(suffix)]
                logger.debug(f"🔍 去除标题后缀: '{resolved_title}' -> '{resolved_title_clean}'")
                break

        best_match = None
        best_score = 0.0

        for fs in planted_foreshadows:
            score = 0.0
            fs_title = fs.get('title', '').strip()
            fs_content = fs.get('content', '').strip()
            fs_category = fs.get('category')
            fs_characters = set(fs.get('related_characters', []))
            fs_plant_chapter = fs.get('plant_chapter_number')

            # 策略1: 标题匹配
            if resolved_title and fs_title:
                if resolved_title == fs_title:
                    score = 1.0
                    logger.debug(f"🎯 标题完全匹配: '{resolved_title}' == '{fs_title}'")
                elif resolved_title_clean and resolved_title_clean == fs_title:
                    score = 0.95
                    logger.debug(f"🎯 清理标题匹配: '{resolved_title_clean}' == '{fs_title}'")
                elif resolved_title in fs_title or fs_title in resolved_title:
                    score = max(score, 0.8)
                    logger.debug(f"🔍 标题包含匹配: '{resolved_title}' <-> '{fs_title}'")
                elif resolved_title_clean and (resolved_title_clean in fs_title or fs_title in resolved_title_clean):
                    score = max(score, 0.75)
                    logger.debug(f"🔍 清理标题包含匹配: '{resolved_title_clean}' <-> '{fs_title}'")
                else:
                    title_overlap = self._calculate_word_overlap(resolved_title, fs_title)
                    score = max(score, title_overlap * 0.7)
                    if title_overlap > 0.3:
                        logger.debug(f'📊 标题词重叠: overlap={title_overlap:.2f}')

            # 策略2: 关键词匹配
            if resolved_keyword and fs_content and resolved_keyword in fs_content:
                score = max(score, 0.75)

            # 策略3: 内容关键词匹配
            if resolved_content and fs_content:
                content_overlap = self._calculate_word_overlap(resolved_content, fs_content)
                score = max(score, content_overlap * 0.6)

            # 策略4: 引用章节号匹配(如果分析结果中有reference_chapter)
            if reference_chapter and fs_plant_chapter and reference_chapter == fs_plant_chapter:
                score += 0.15  # 加分

            # 策略5: 分类匹配
            if resolved_category and fs_category and resolved_category == fs_category:
                score += 0.1

            # 策略6: 相关角色匹配
            if resolved_characters and fs_characters:
                character_overlap = len(resolved_characters & fs_characters) / max(len(resolved_characters | fs_characters), 1)
                score += character_overlap * 0.1

            # 更新最佳匹配
            if score > best_score and score >= min_similarity:
                best_score = score
                best_match = fs

        if best_match:
            logger.info(f"🎯 内容匹配成功: '{resolved_title}' -> '{best_match.get('title')}' (相似度: {best_score:.2f})")

        return best_match

    def _calculate_word_overlap(self, text1: str, text2: str) -> float:
        """
        计算两个文本的词重叠度

        使用字符级别的 n-gram 相似度计算

        Args:
            text1: 文本1
            text2: 文本2

        Returns:
            0-1之间的相似度分数
        """
        if not text1 or not text2:
            return 0.0

        # 使用2-gram和3-gram
        def get_ngrams(text: str, n: int) -> set:
            text = text.lower().replace(' ', '').replace('\n', '')
            if len(text) < n:
                return {text}
            return {text[i : i + n] for i in range(len(text) - n + 1)}

        # 计算2-gram相似度
        ngrams1_2 = get_ngrams(text1, 2)
        ngrams2_2 = get_ngrams(text2, 2)
        overlap_2 = len(ngrams1_2 & ngrams2_2) / max(len(ngrams1_2 | ngrams2_2), 1)

        # 计算3-gram相似度
        ngrams1_3 = get_ngrams(text1, 3)
        ngrams2_3 = get_ngrams(text2, 3)
        overlap_3 = len(ngrams1_3 & ngrams2_3) / max(len(ngrams1_3 | ngrams2_3), 1)

        # 综合评分(3-gram权重更高,因为更精确)
        return overlap_2 * 0.4 + overlap_3 * 0.6


# 创建全局服务实例
