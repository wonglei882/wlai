"""自我进化系统：生成后自评 + 经验库 + 偏好建模

L4 方向3：经验提炼 + 遗忘
- 经验去重：相似度 > 0.8 合并，count + 1
- 经验衰减：30 天未命中 → 置信度指数衰减
- 规则提升：count >= 5 → 提升为 expert rule 参与决策
"""

import re
import math
from datetime import datetime
import logging
from app.services.pm.feature_config import get_pm_feature_config

logger = logging.getLogger(__name__)

# L4 方向3 常量（相似度阈值/衰减半衰期来自 pm_features.yaml: optional.self_evolution）
_evolve_cfg = get_pm_feature_config('optional.self_evolution') or {}
SIMILARITY_THRESHOLD = _evolve_cfg.get('similarity_threshold', 0.8)  # 相似度 > 此值时合并经验
DECAY_HALF_LIFE_DAYS = _evolve_cfg.get('decay_half_life_days', 30)  # 30 天半衰期
DECAY_THRESHOLD = 0.2  # 置信度低于此值 → 归档（不删除）
RULE_PROMOTION_THRESHOLD = 5  # 同类经验累积到此数 → 提升为规则


# ======================================================================
# 1. 生成质量自评
# ======================================================================
class SelfCritique:
    """输出后自动评估质量，低分标记问题点供用户参考。"""

    @staticmethod
    def evaluate(content: str, chapter_number: int = 0, target_words: int = 3000) -> dict:
        """
        章节生成后自动评估。
        Returns: {score, issues, details}
        """
        issues = []
        details = {}
        score = 1.0

        if not content or not content.strip():
            return {'score': 0, 'issues': ['生成内容为空'], 'details': {}, 'should_retry': True}

        length = len(content)

        # ---- 篇幅得分：连续函数替代硬阈值 ----
        def _length_penalty(ratio: float) -> float:
            """连续扣分：达标不扣；0→0.35；0.6→0.1；1.0→0"""
            if ratio >= 1.0:
                return 0.0
            if ratio >= 0.6:
                return 0.1 * (1.0 - ratio) / 0.4
            # 0~0.6 区间线性，ratio=0 时扣 0.35
            return 0.35 * (0.6 - ratio) / 0.6 + 0.1

        details['length'] = length
        ratio = length / target_words
        penalty = _length_penalty(ratio)
        score -= penalty
        if ratio < 0.6:
            issues.append(f'篇幅{int(ratio * 100)}%目标（{length}字），偏低')

        # ---- 开头500字钩子 ----
        opening = content[:500]
        hook_keywords = [
            '突然',
            '但是',
            '然而',
            '没想到',
            '怎么回事',
            '什么',
            '危险',
            '杀',
            '死',
            '秘密',
            '发现',
            '震惊',
            '不可能',
            '为什么',
            '站住',
            '别动',
        ]
        has_hook = any(kw in opening for kw in hook_keywords)
        details['has_opening_hook'] = has_hook
        if not has_hook and length > 800:
            issues.append('开篇500字可能缺少钩子/悬念，读者容易划走')
            score -= 0.1

        # ---- 重复段落检测：连续函数替代硬阈值 ----
        def _paragraph_penalty(ratio_unique: float) -> float:
            """连续扣分：ratio_unique=1.0→0；0→0.15"""
            return max(0.0, 0.15 * (1.0 - ratio_unique))

        if length > 500:
            paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
            if paragraphs:
                unique = len(set(paragraphs))
                ratio_unique = unique / len(paragraphs)
                details['paragraph_unique_ratio'] = round(ratio_unique, 2)
                penalty = _paragraph_penalty(ratio_unique)
                if penalty > 0.05:
                    score -= penalty
                    issues.append(f'段落重复率偏高(唯一比{ratio_unique:.0%})')

        # ---- 结尾钩子 ----
        ending = content[-300:]
        ending_hook_kws = ['…', '...', '突然', '这时', '就在这时', '然而', '没想到', '究竟', '什么']
        has_ending_hook = any(kw in ending for kw in ending_hook_kws)
        details['has_ending_hook'] = has_ending_hook
        if not has_ending_hook and length > 500:
            issues.append('结尾可能缺少钩子，读者可能不想点下一章')
            score -= 0.05

        # ---- AI套话 ----
        filler_patterns = [
            (r'总的来说|综上所述|总而言之', '总结性套话'),
            (r'让我们(看看|继续|回到)', '作者旁白'),
            (r'值得一提的是|需要注意的是', 'AI常见过渡'),
            (r'他(?:们)?(?:就|突然|终于|早已|瞬间|立刻|猛地)?(?:知道|明白|意识到)', '过度心理描写提示词'),
        ]
        ai_marks = []
        for pat, label in filler_patterns:
            matches = re.findall(pat, content)
            if matches:
                ai_marks.append(f'{label}({len(matches)}处)')
                score -= 0.03 * min(len(matches), 5)
        if ai_marks:
            issues.append(f'检测到AI常见表达：{"、".join(ai_marks[:3])}')
            details['ai_filler'] = ai_marks

        score = max(0.1, round(score, 2))
        return {
            'score': score,
            'issues': issues[:5],
            'details': details,
            'should_retry': score < 0.4,
        }


# ======================================================================
# 2. 经验库（复用项目已有的 ChromaDB）
# ======================================================================
# 调用方：pm_agent_decision.py L4 决策反射注入（get_promoted_rules）。
# 该类不通过 __init__.py 导出，需调用方显式 import。
class BehaviorMemory:
    """
    记录成功/失败的生成案例，下次生成时注入相似案例作为 few-shot 参考。
    复用 MemoryService 的 ChromaDB 和 embedding 模型。
    """

    _collection = None

    @classmethod
    def _get_collection(cls):
        """获取Collection

        Args:
            cls:

        Returns:
            None
        """
        if cls._collection is not None:
            return cls._collection
        try:
            from app.services.memory_service import memory_service

            # 用已有 chroma 客户端
            if hasattr(memory_service, 'client'):
                cls._collection = memory_service.client.get_or_create_collection(
                    name='experience',
                    metadata={'hnsw:space': 'cosine'},
                )
                logger.info('✅ BehaviorMemory: experience 集合就绪')
                return cls._collection
        except Exception as e:
            logger.warning(f'BehaviorMemory 初始化失败: {e}')
        return None

    @classmethod
    def record(
        cls, chapter_number: int, project_id: str, outline_summary: str, generated_content: str, critique_score: float, feedback: str = 'success'
    ):
        """
        记录一次生成经验。
        feedback: "success" / "failure" / "revised"

        L4 方向3：入库前做相似度去重。
        相似度 > SIMILARITY_THRESHOLD 的合并（count + 1），不新增条目。
        """
        col = cls._get_collection()
        if not col:
            return
        try:
            doc_text = outline_summary[:500] if outline_summary else f'第{chapter_number}章生成'
            now_iso = datetime.now().isoformat()

            # --- 经验去重：查询相似经验 ---
            merged = cls._try_merge_similar(
                col,
                doc_text,
                project_id,
                feedback,
                critique_score,
                generated_content,
                now_iso,
            )
            if merged:
                logger.info(f'  ✅ 合并相似经验: score={critique_score} (count updated)')
                return

            # --- 新增经验条目 ---
            doc_id = f'exp_{project_id[:8]}_{chapter_number}_{col.count() + 1}'
            meta = {
                'project_id': project_id[:12],
                'chapter_number': str(chapter_number),
                'feedback': feedback,
                'score': str(critique_score),
                'content_preview': generated_content[:200] if generated_content else '',
                'timestamp': now_iso,
                # L4 方向3 新增字段
                'count': '1',
                'confidence': '1.0',
                'last_hit_at': now_iso,
                'promoted': 'false',
            }
            col.add(ids=[doc_id], documents=[doc_text], metadatas=[meta])
            logger.info(f'  ✅ 记录生成经验: {doc_id} score={critique_score}')
        except Exception as e:
            logger.warning(f'记录经验失败: {e}')

    @classmethod
    def _try_merge_similar(
        cls,
        col,
        doc_text: str,
        project_id: str,
        feedback: str,
        critique_score: float,
        generated_content: str,
        now_iso: str,
    ) -> bool:
        """查询相似经验，相似度 > SIMILARITY_THRESHOLD 则合并。"""
        try:
            where_clause = {'feedback': feedback}
            if project_id:
                where_clause['project_id'] = project_id[:12]
            results = col.query(
                query_texts=[doc_text],
                n_results=5,
                where=where_clause,
            )
            metas = results.get('metadatas', [[]])[0]
            ids = results.get('ids', [[]])[0]
            dists = results.get('distances', [[]])[0]

            for i, (doc_id, dist) in enumerate(zip(ids, dists, strict=False)):
                # ChromaDB cosine distance → similarity: sim = 1 - dist
                similarity = 1.0 - dist if dist is not None else 0.0
                if similarity > SIMILARITY_THRESHOLD:
                    # 合并：更新 count, confidence, last_hit_at
                    meta = metas[i] if i < len(metas) else {}
                    count = int(meta.get('count', '1')) + 1
                    confidence = float(meta.get('confidence', '1.0'))
                    # 命中时刷新置信度
                    confidence = min(1.0, confidence + 0.1)
                    meta['count'] = str(count)
                    meta['confidence'] = str(confidence)
                    meta['last_hit_at'] = now_iso
                    meta['score'] = str(critique_score)
                    # 更新文档内容（取较新的内容）
                    col.update(
                        ids=[doc_id],
                        documents=[doc_text],
                        metadatas=[meta],
                    )
                    # 检查是否达到规则提升阈值
                    if count >= RULE_PROMOTION_THRESHOLD:
                        meta['promoted'] = 'true'
                        col.update(ids=[doc_id], metadatas=[meta])
                        logger.info(f'  📈 经验提升为规则: {doc_id} (count={count})')
                    return True
        except Exception as e:
            logger.debug(f'经验去重查询失败: {e}')
        return False

    @classmethod
    def get_examples(cls, current_outline: str, project_id: str = '', top_k: int = 2) -> str:
        """检索相似成功案例，返回可注入 prompt 的文本。"""
        col = cls._get_collection()
        if not col or col.count() == 0:
            return ''
        try:
            where_clause = {'feedback': 'success'}
            if project_id:
                where_clause['project_id'] = project_id[:12]
            results = col.query(
                query_texts=[current_outline[:500]],
                n_results=min(top_k * 2, col.count()),
                where=where_clause,
            )
            docs = results.get('documents', [[]])[0]
            metas = results.get('metadatas', [[]])[0]
            if not docs:
                return ''
            examples = []
            for i, doc in enumerate(docs):
                meta = metas[i] if i < len(metas) else {}
                preview = meta.get('content_preview', doc[:100])
                ch = meta.get('chapter_number', '?')
                examples.append(f'【参考-第{ch}章】\n章纲：{doc[:120]}...\n有效写法：{preview[:120]}...\n')
            return '\n'.join(examples[:top_k])
        except Exception as e:
            logger.warning(f'检索经验失败: {e}')
            return ''

    # ==================================================================
    # L4 方向3：经验衰减 + 规则提升
    # ==================================================================

    @classmethod
    def apply_decay(cls) -> int:
        """
        对所有经验条目执行置信度衰减。

        - 30 天未命中(last_hit_at) → 置信度按指数衰减
        - 置信度 < DECAY_THRESHOLD → 标记 archived（不删除）
        - 已提升为规则的经验有保底权重 0.3，不被衰减到 0

        Returns:
            归档的经验条目数
        """
        col = cls._get_collection()
        if not col or col.count() == 0:
            return 0
        try:
            # 获取所有经验
            all_data = col.get()
            ids = all_data.get('ids', [])
            metas = all_data.get('metadatas', [])
            if not ids:
                return 0

            now = datetime.now()
            archived_count = 0
            to_update_ids = []
            to_update_metas = []

            for doc_id, meta in zip(ids, metas, strict=False):
                last_hit_str = meta.get('last_hit_at') or meta.get('timestamp', '')
                if not last_hit_str:
                    continue

                try:
                    last_hit = datetime.fromisoformat(last_hit_str)
                except Exception as e:
                    logger.debug(f'经验衰减跳过无法解析的时间: {e}')
                    continue

                days_since_hit = (now - last_hit).days
                if days_since_hit <= 0:
                    continue

                confidence = float(meta.get('confidence', '1.0'))
                promoted = meta.get('promoted', 'false') == 'true'

                # 指数衰减：conf *= 0.5^(days / half_life)
                decay_factor = math.pow(0.5, days_since_hit / DECAY_HALF_LIFE_DAYS)
                new_confidence = confidence * decay_factor

                # 规则有保底权重，不被衰减到 0
                if promoted:
                    new_confidence = max(0.3, new_confidence)
                elif new_confidence < DECAY_THRESHOLD:
                    new_confidence = 0.0
                    meta['archived'] = 'true'
                    archived_count += 1

                meta['confidence'] = f'{new_confidence:.4f}'
                to_update_ids.append(doc_id)
                to_update_metas.append(meta)

            if to_update_ids:
                col.update(ids=to_update_ids, metadatas=to_update_metas)
                logger.info(f'  📉 经验衰减完成: {len(to_update_ids)} 条更新, {archived_count} 条归档')
            return archived_count
        except Exception as e:
            logger.warning(f'经验衰减失败: {e}')
            return 0

    @classmethod
    def get_promoted_rules(cls, project_id: str = '', top_k: int = 3) -> list:
        """
        获取已提升为规则的经验，用于决策评分。

        Returns:
            规则列表 [{doc_id, text, confidence, count, score}, ...]
        """
        col = cls._get_collection()
        if not col or col.count() == 0:
            return []
        try:
            all_data = col.get(where={'promoted': 'true'})
            ids = all_data.get('ids', [])
            docs = all_data.get('documents', [])
            metas = all_data.get('metadatas', [])

            rules = []
            for doc_id, doc, meta in zip(ids, docs, metas, strict=False):
                if project_id and meta.get('project_id', '') != project_id[:12]:
                    continue
                confidence = float(meta.get('confidence', '0.5'))
                # 跳过低置信度规则
                if confidence < 0.3:
                    continue
                rules.append(
                    {
                        'doc_id': doc_id,
                        'text': doc[:200],
                        'confidence': confidence,
                        'count': int(meta.get('count', '1')),
                        'score': float(meta.get('score', '0.5')),
                    }
                )

            # 按置信度降序
            rules.sort(key=lambda r: r['confidence'], reverse=True)
            return rules[:top_k]
        except Exception as e:
            logger.warning(f'获取规则失败: {e}')
            return []


# ======================================================================
# 3. 偏好建模
# 已迁移至 pm_preference_learner.py（DB 持久化），此处类已删除
# 2026-08-18: UserProfile 类删除（无外部调用，数据迁移至 pm_user_profiles 表）
# ======================================================================
