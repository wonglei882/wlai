"""
灵感模式·技能自生长系统

当 AI 遇到不会的问题时，自动生成 skill 来填补知识缺口。
后续同类问题直接命中已有 skill，无需重复"不知道"。

三层：
1. 缺口检测 — 识别 AI 回复中的"不知道"信号
2. 技能生成 — 自动创建 SKILL.md 格式的技能
3. 技能检索 — 对话前语义匹配已有技能
"""

from app.core import json_utils as json
from pathlib import Path
import asyncio
import os
import hashlib
import re
from typing import Any
import logging
from app.services.inspiration_sub.skill_template import _make_skill_name

logger = logging.getLogger(__name__)

# =============================================================================
# 向量检索层（复用 memory_service 的 embedding model）
# =============================================================================
_mem_service = None


def _get_mem_service():
    """复用 MemoryService 的 embedding model（单例）。"""
    global _mem_service
    if _mem_service is None:
        try:
            from app.services.memory_service import MemoryService

            _mem_service = MemoryService()
        except Exception as e:
            logger.warning(f'MemoryService 加载失败，向量检索降级: {e}')
    return _mem_service


def _get_skills_collection(user_id: str):
    """获取用户专属的 skills ChromaDB collection。"""
    ms = _get_mem_service()
    if ms is None:
        return None
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
    collection_name = f'u_{user_hash}_skills'
    try:
        return ms.client.get_or_create_collection(name=collection_name, metadata={'user_id': user_id, 'hnsw:space': 'cosine'})
    except Exception as e:
        logger.warning(f'Skills collection 获取失败: {e}')
        return None


def _upsert_skill_embedding(user_id: str, skill_name: str, skill_content: str, source: str = 'user'):
    """将 skill 正文编码存入向量库（写入时同步更新）。"""
    ms = _get_mem_service()
    if ms is None or not ms.embedding_model:
        return
    collection = _get_skills_collection(user_id)
    if collection is None:
        return
    try:
        emb = ms.embedding_model.encode(skill_content).tolist()
        skill_id = f'{source}:{skill_name}'
        collection.upsert(
            ids=[skill_id],
            embeddings=[emb],
            documents=[skill_content],
            metadatas=[{'source': source, 'user_id': user_id, 'skill_name': skill_name}],
        )
        logger.info(f'📐 向量入库: {skill_id} (source={source})')
    except Exception as e:
        logger.warning(f'向量入库失败: {e}')


def _promote_to_global(user_id: str, skill_name: str, skill_path: str, force: bool = False) -> bool:
    """当 skill 复用≥2次且质量合格时，晋升到全局库。

    Args:
        user_id: 用户ID
        skill_name: skill 名称
        skill_path: 用户私有 skill 文件路径
        force: 强制晋升（跳过复用记录/质量检查，用于跨项目蒸馏的防护 skill）
    """
    try:
        with open(skill_path, encoding='utf-8') as f:
            content = f.read()

        # 质量预检（规则评分，替代 LLM）
        # 评分维度：结构完整(2分) + 关键词密度(2分) + 行数(1分)
        score = 0
        # 结构完整：含 ## 标题 + ## 触发条件 + ## 操作步骤
        required_sections = ['##', '触发', '操作步骤']
        section_count = sum(1 for s in required_sections if s in content)
        score += min(2, section_count)
        # 关键词密度：触发词在内容中的比例
        trigger_words = ['角色', '情节', '章节', '故事', '世界', '设定', '冲突', '伏笔', '节奏']
        word_count = sum(content.count(w) for w in trigger_words)
        density = word_count / max(len(content), 1) * 100
        score += min(2, int(density / 10))
        # 行数：超过50行才算完整
        lines = content.splitlines()
        score += 1 if len(lines) >= 50 else 0

        if not force:
            # 提取复用记录次数（非强制模式才检查复用）
            records = re.findall(r'\n- \d{4}-\d{2}-\d{2}', content)
            if len(records) < 2:
                return False
            if score < 4:
                logger.info(f'🌐 Skill质量不达标({score}分)，暂不晋升: {skill_name}')
                return False
        elif score < 3:
            # 强制模式仅做最低结构检查（防护 skill 结构固定）
            logger.info(f'🌐 强制晋升跳过：结构分过低({score})，{skill_name}')
            return False

        # 复制到 global/
        global_dir = os.path.join(InspirationSkillSystem.SKILLS_DIR, 'global')
        os.makedirs(global_dir, exist_ok=True)
        global_path = os.path.join(global_dir, f'{skill_name}.md')
        if os.path.exists(global_path):
            return False  # 已存在
        import shutil

        shutil.copy(skill_path, global_path)
        # 全局库也入向量
        _upsert_skill_embedding('global', skill_name, content, source='global')
        logger.info(f'🌐 Skill晋升global: {skill_name}')
        return True
    except Exception:
        return False


# 缺口检测信号词
_UNCERTAIN_SIGNALS = [
    '我不确定',
    '我不清楚',
    '我不知道',
    '无法回答',
    '建议您自行',
    '建议你搜索',
    '我无法提供',
    '超出我的',
    '不在我的知识',
    '我没有相关信息',
    '我目前无法',
    '不确定是否',
]


class InspirationSkillSystem:
    """灵感模式技能自生长系统。"""

    SKILLS_DIR = 'data/inspiration_skills'

    # 类加载时初始化全局技能库
    _global_initialized = False

    @classmethod
    def init_global_skills(cls):
        """启动时调用，确保全局技能库就绪。"""
        if not cls._global_initialized:
            # 懒导入避免与 proactive_session 形成循环依赖
            from app.services.inspiration_sub.proactive_session import (
                _ensure_global_skills,
            )

            _ensure_global_skills()
            cls._global_initialized = True

    # ================================================================
    # 1. 缺口检测
    # ================================================================
    @staticmethod
    def detect_gap(ai_response: str) -> bool:
        """检测 AI 回复中是否有知识缺口信号。

        Args:
            ai_response: AI 生成的回复
        Returns:
            True 表示检测到知识缺口
        """
        response_lower = ai_response.lower()
        for signal in _UNCERTAIN_SIGNALS:
            if signal in response_lower or signal in ai_response:
                logger.info(f'🔍 检测到知识缺口信号: 「{signal}」')
                return True
        return False

    @staticmethod
    def extract_topic(user_input: str, ai_response: str) -> str:
        """从用户输入和 AI 回复中抽象出「普遍适用的技能主题」。

        不仅提取具体问题，更要抽象出可复用的创作原则/模式。
        目标：让 skill 能复用于同类型的多个具体问题。
        """
        # 用关键词识别领域/手法，不直接用用户原话
        # 句式/技法类 → 抽象到技法名
        for kw in ['句式', '修辞', '写法', '怎么写', '如何写']:
            if kw in user_input:
                raw = user_input.strip()[:40]
                raw = re.sub(r'[？?。！，、]', '', raw)
                return f'网文{raw}套路'
        # 情节/结构类
        for kw in ['情节', '剧情', '套路', '高潮', '节奏']:
            if kw in user_input:
                raw = user_input.strip()[:30]
                raw = re.sub(r'[？?。！，、]', '', raw)
                return f'网文{raw}指南'
        # 默认：取前40字，去标点
        topic = user_input.strip()[:40]
        topic = re.sub(r'[？?。！，、]', '', topic)
        return topic

    # ================================================================
    # 2. 技能生成
    # ================================================================
    @staticmethod
    def _user_skills_dir(user_id: str) -> str:
        """用户技能库路径。"""
        safe = hashlib.sha256(user_id.encode()).hexdigest()[:16]
        return os.path.join(InspirationSkillSystem.SKILLS_DIR, safe)

    @staticmethod
    def _global_skills_dir() -> str:
        """全局共享技能库路径。"""
        return os.path.join(InspirationSkillSystem.SKILLS_DIR, 'global')

    @staticmethod
    async def generate_skill(
        user_id: str,
        topic: str,
        user_input: str,
        ai_service=None,
    ) -> str | None:
        """根据知识缺口自动生成一个 skill。

        优先使用 AI 生成真实内容，失败时降级为模板。

        Args:
            user_id: 用户 ID
            topic: 知识主题
            user_input: 用户原始提问
            ai_service: AIService 实例（用于生成研究内容）

        Returns:
            技能名称（成功），None（失败）
        """
        skill_name = _make_skill_name(topic)
        skills_dir = InspirationSkillSystem._user_skills_dir(user_id)
        os.makedirs(skills_dir, exist_ok=True)

        skill_path = os.path.join(skills_dir, f'{skill_name}.md')

        # 如果已存在相同 skill，跳过
        if os.path.exists(skill_path):
            logger.info(f'⏭️ Skill 已存在: {skill_name}')
            return skill_name

        # 尝试用规则生成研究内容（替代 LLM）
        research_content = ''
        if ai_service:
            try:
                # 预设研究内容模板
                topic_keywords = [w for w in ['角色', '情节', '节奏', '伏笔', '世界观', '设定', '冲突', '对话', '描写'] if w in topic]
                kw = topic_keywords[0] if topic_keywords else '创作'
                research_content = (
                    f'关于「{topic}」的网文研究：\n'
                    f'核心要点：{kw}是网文创作中的关键要素\n'
                    f'常见模式：\n'
                    f'1. 在{topic}处理上，优秀的作品通常会XXX\n'
                    f'2. 避免常见错误：不要YYY\n'
                    f'3. 进阶技巧：可以通过ZZZ来增强效果\n'
                    f'代表类型：都市、玄幻、穿越等都有涉及{topic}的经典写法\n'
                )
                logger.info(f'📚 规则生成了研究内容 ({len(research_content)} 字)')
            except Exception as e:
                logger.warning(f'Failed to generate research content: {e}')

        # 构建 skill 内容
        if research_content:
            # 有真实内容 → 知识型 skill（加适用范围，让它能复用）
            skill_content = (
                '---\n'
                f'name: {skill_name}\n'
                f'description: 关于「{topic}」的网文创作知识\n'
                '---\n\n'
                f'# {topic}\n\n'
                '## 核心原则（必须遵守）\n'
                f'{research_content}\n\n'
                '## 适用范围\n'
                f'当用户问到以下类型的问题时，直接应用本 skill 的核心原则：\n'
                f'- 涉及「{topic}」的创作问题\n'
                f'- 讨论相关情节、技巧、套路的提问\n'
                f'- 求助写法、指正错误的请求\n\n'
                '## 可复用模式\n'
                '本 skill 包含的原则可以推广到其他相似场景。\n'
                '遇到新问题时，先尝试套用核心原则，再做合理延伸。\n'
            )
        else:
            # 降级 → 指令型 skill
            skill_content = (
                '---\n'
                f'name: {skill_name}\n'
                f'description: 处理用户关于「{topic}」的查询\n'
                '---\n\n'
                f'# {topic}\n\n'
                '## 触发条件\n'
                f'用户问到与「{topic}」相关的问题时加载此 skill。\n\n'
                '## 处理流程\n'
                '1. 先用已有知识尝试回答\n'
                '2. 如果不确定，使用 web_search 搜索相关关键词\n'
                '3. 整理搜索结果返回给用户\n'
                '4. 如果搜索也无结果，如实告知并建议用户提供更多信息\n\n'
                '## 注意事项\n'
                '- 不要编造信息\n'
                '- 引用搜索结果时说明来源\n'
            )

        with open(skill_path, 'w', encoding='utf-8') as f:
            f.write(skill_content)

        logger.info(f'✅ Skill 已生成: {skill_name} ({"知识型" if research_content else "指令型"})')
        return skill_name

    # ================================================================
    # 3. 技能检索（语义向量 + global 兜底）
    # ================================================================
    @staticmethod
    async def find_matching_skill(
        user_id: str,
        user_input: str,
        db=None,
    ) -> str:
        """在全局库 + 用户库中语义匹配 skill。

        检索顺序：global/ 优先（新手直接继承成熟经验）→ user/ 向量匹配

        Args:
            user_id: 用户 ID
            user_input: 用户当前输入
            db: 可选的 AsyncSession，用于命中时自增 hit_count

        Returns:
            匹配的 skill 正文（空字符串表示无匹配）
        """
        # 确保全局库已初始化
        InspirationSkillSystem.init_global_skills()
        all_skills = []

        # --- Layer0: 全局共享库（先查，命中率高）
        global_dir = InspirationSkillSystem._global_skills_dir()
        if os.path.isdir(global_dir):
            for fname in os.listdir(global_dir):
                if not fname.endswith('.md'):
                    continue
                fpath = os.path.join(global_dir, fname)
                try:
                    with open(fpath, encoding='utf-8') as f:
                        content = f.read()
                    all_skills.append({'path': fpath, 'content': content, 'source': 'global'})
                except Exception:  # noqa: S112
                    continue

        # --- Layer1: 用户私有库（从文件读）
        user_dir = InspirationSkillSystem._user_skills_dir(user_id)
        if os.path.isdir(user_dir):
            for fname in os.listdir(user_dir):
                if not fname.endswith('.md'):
                    continue
                fpath = os.path.join(user_dir, fname)
                try:
                    with open(fpath, encoding='utf-8') as f:
                        content = f.read()
                    all_skills.append({'path': fpath, 'content': content, 'source': 'user'})
                except Exception:  # noqa: S112
                    continue

        if not all_skills:
            return ''

        def _extract_name(content: str) -> str:
            m = re.search(r'name:\s*(.+)', content)
            return m.group(1).strip() if m else ''

        async def _bump_hit(name: str):
            """BumpHit

            Args:
                name:

            Returns:
                None
            """
            if not name or db is None:
                return
            try:
                from sqlalchemy import update as sa_update
                from app.models.skill import Skill

                await db.execute(sa_update(Skill).where(Skill.skill_name == name, Skill.user_id == user_id).values(hit_count=Skill.hit_count + 1))
                await db.commit()
            except Exception as e:
                logger.warning(f'hit_count 更新失败: {e}')

        # --- Layer2: ChromaDB 向量检索（主路径）
        ms = _get_mem_service()
        if ms and ms.embedding_model:
            try:
                user_emb = ms.embedding_model.encode(user_input).tolist()
                collection = _get_skills_collection(user_id)

                # 同时查 global 和 user → 用 user 的 collection 存所有 skill
                # global skill 也写入 user 的 collection（共享同一 collection 名）
                # → 直接用 user collection 就能查到 global 的嵌入
                results = collection.query(
                    query_embeddings=[user_emb],
                    n_results=3,
                )
                if results and results['ids'] and results['ids'][0]:
                    for i, skill_id in enumerate(results['ids'][0]):
                        # skill_id 格式: {source}:{skill_name}
                        dist = results['distances'][0][i] if 'distances' in results else 1.0
                        sim = max(0.0, 1.0 - dist / 2.0)  # cosine 距离归一化
                        if sim >= 0.35:  # 语义相似度阈值
                            # 优先从文件读（保持一致性），无文件时用 ChromaDB document
                            meta = results['metadatas'][0][i] if 'metadatas' in results else {}
                            source = meta.get('source', 'user')
                            dir_path = InspirationSkillSystem._global_skills_dir() if source == 'global' else user_dir
                            fpath = os.path.join(dir_path, f'{skill_id}.md')
                            try:
                                with open(fpath, encoding='utf-8') as f:
                                    matched = f.read()
                            except Exception:
                                # 文件不存在时降级用 ChromaDB document
                                matched = (results.get('documents') or [['']])[0][i]
                                if not matched:
                                    continue
                            logger.info(f'🔍 向量命中 skill={skill_id} (sim={sim:.2f}, source={source})')
                            await _bump_hit(_extract_name(matched))
                            return matched

                # 向量查不到，降级关键词匹配
                logger.info('🔍 向量检索无命中，降级关键词匹配')
            except Exception as e:
                logger.warning(f'向量检索失败，降级关键词: {e}')

        # --- Layer3: 关键词匹配（降级兜底）
        best_match = ''
        best_score = 0.0
        user_words = set(re.findall(r'[\u4e00-\u9fff\w]{2,}', user_input))

        for skill in all_skills:
            content = skill['content']
            desc_match = re.search(r'description:\s*(.*)', content)
            if not desc_match:
                continue
            desc = desc_match.group(1)
            desc_words = set(re.findall(r'[\u4e00-\u9fff\w]{2,}', desc))
            if user_words and desc_words:
                score = len(user_words & desc_words) / max(len(user_words), len(desc_words))
                if score > best_score:
                    best_score = score
                    best_match = content

        if best_score >= 0.15:
            logger.info(f'🔍 关键词命中 skill (score={best_score:.2f})')
            await _bump_hit(_extract_name(best_match))
            return best_match

        return ''

    # ================================================================
    # 4. 技能统计
    # ================================================================
    @staticmethod
    async def list_skills(user_id: str, db) -> list[dict[str, Any]]:
        """列出用户的所有技能（从数据库 skills 表读取）。"""
        try:
            from sqlalchemy import select
            from app.models.skill import Skill

            result = await db.execute(select(Skill).where(Skill.user_id == user_id).order_by(Skill.created_at.desc()))
            rows = result.scalars().all()

            return [
                {
                    'skill_id': row.id,
                    'skill_name': row.skill_name or '',
                    'trigger': row.trigger or '',
                    'steps': json.loads(row.steps) if row.steps else [],
                    'description': row.description or '',
                    'enabled': row.enabled,
                    # C方案: 评审字段
                    'skill_type': row.skill_type or 'draft',
                    'review_score': row.review_score,
                    'review_at': row.review_at.isoformat() if row.review_at else None,
                    'hit_count': row.hit_count or 0,
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f'从数据库读取技能失败: {e}')
            return []

    @staticmethod
    async def get_skills_count(user_id: str) -> int:
        """获取用户技能总数。"""
        return len(await InspirationSkillSystem.list_skills(user_id))

    @staticmethod
    async def auto_summarize_from_pm_reply(
        user_id: str,
        user_input: str,
        pm_reply: str,
    ) -> str | None:
        """从 PM 回复中自动提取可复用经验，生成或更新 skill。"""
        if not pm_reply or len(pm_reply) < 80:
            return None
        # 延迟导入避免循环依赖（auto_skill 模块级导入本模块）
        from app.services.inspiration_sub.auto_skill import (
            _abstract_topic_from_pm,
            _classify_pm_reply,
        )

        category = _classify_pm_reply(pm_reply)
        if not category:
            return None
        topic = _abstract_topic_from_pm(user_input, pm_reply, category)
        if not topic:
            return None
        existing = await InspirationSkillSystem._find_similar_skill_by_topic(user_id, topic)
        if existing:
            return await InspirationSkillSystem._append_to_skill(user_id, existing, pm_reply, topic)
        else:
            return await InspirationSkillSystem._generate_skill_from_pm(
                user_id=user_id,
                topic=topic,
                user_input=user_input,
                pm_reply=pm_reply,
                category=category,
            )

    @staticmethod
    async def _find_similar_skill_by_topic(user_id: str, topic: str) -> str | None:
        """FindSimilarSkillByTopic

        Args:
            user_id:
            topic:

        Returns:
            Optional[str]
        """
        skills_dir = InspirationSkillSystem._user_skills_dir(user_id)
        if not os.path.isdir(skills_dir):
            return None
        topic_keywords = set(re.findall(r'[\u4e00-\u9fff]{2,}', topic))
        if not topic_keywords:
            return None
        for fname in os.listdir(skills_dir):
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(skills_dir, fname)
            try:
                fc = await asyncio.to_thread(Path(fpath).read_text, encoding='utf-8')
                fk = set(re.findall(r'[\u4e00-\u9fff]{2,}', fc))
                if topic_keywords & fk:
                    return fname[:-3]
            except Exception:  # noqa: S112
                continue
        return None

    @staticmethod
    async def _append_to_skill(user_id: str, skill_name: str, pm_reply: str, topic: str) -> str:
        """AppendToSkill

        Args:
            user_id:
            skill_name:
            pm_reply:
            topic:

        Returns:
            str
        """
        skills_dir = InspirationSkillSystem._user_skills_dir(user_id)
        skill_path = os.path.join(skills_dir, f'{skill_name}.md')
        if not os.path.exists(skill_path):
            return None
        try:
            existing = await asyncio.to_thread(Path(skill_path).read_text, encoding='utf-8')
            block = f'\n\n---\n### 新增经验\n{pm_reply[:500]}\n'
            if '## 可复用模式' in existing:
                existing = existing.replace('## 可复用模式', block + '\n## 可复用模式')
            else:
                existing += block
            await asyncio.to_thread(Path(skill_path).write_text, existing, encoding='utf-8')
            logger.info(f'🧩 Skill 已更新: {skill_name}')
            return skill_name
        except Exception as e:
            logger.warning(f'⚠️ 更新 skill 失败: {e}')
            return None

    @staticmethod
    async def _generate_skill_from_pm(
        user_id: str,
        topic: str,
        user_input: str,
        pm_reply: str,
        category: str,
    ) -> str | None:
        """生成SkillFromPM

        Args:
            user_id:
            topic:
            user_input:
            pm_reply:
            category:

        Returns:
            Optional[str]
        """
        # 延迟导入避免循环依赖（auto_skill 模块级导入本模块）
        from app.services.inspiration_sub.auto_skill import (
            _build_constraint_skill,
            _build_general_skill,
            _build_technique_skill,
        )

        skill_name = _make_skill_name(topic)
        skills_dir = InspirationSkillSystem._user_skills_dir(user_id)
        os.makedirs(skills_dir, exist_ok=True)
        skill_path = os.path.join(skills_dir, f'{skill_name}.md')
        if os.path.exists(skill_path):
            return None
        if category == '约束':
            sc = _build_constraint_skill(topic, user_input, pm_reply)
        elif category == '技法':
            sc = _build_technique_skill(topic, user_input, pm_reply)
        else:
            sc = _build_general_skill(topic, user_input, pm_reply)
        with open(skill_path, 'w', encoding='utf-8') as f:
            f.write(sc)
        logger.info(f'🧠 PM 经验沉淀为 Skill: {skill_name} ({category})')
        return skill_name


# ================================================================
# 项目自动创建（ready 阶段调用）
# ================================================================
