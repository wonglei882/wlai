"""事件总线监听动作——关系网自动更新。

从 event_bus_listeners.py 拆出（2026-08-25），职责单一：
- _auto_update_relationships：提取角色互动并更新 CharacterRelationship 表
- _POSITIVE_INTERACTION / _NEGATIVE_INTERACTION / _NEUTRAL_INTERACTION：互动词表

日志规范与主文件一致：
- routine 处理错误 → logger.info（非阻塞）
- 真实数据问题 → logger.warning
"""

import logging

logger = logging.getLogger(__name__)


# ===== 关系网自动更新 =====

# 正面互动词（增加亲密度）
_POSITIVE_INTERACTION = [
    '拥抱',
    '握手',
    '微笑',
    '感谢',
    '道歉',
    '承诺',
    '保护',
    '帮助',
    '安慰',
    '鼓励',
    '支持',
    '信任',
    '欣赏',
    '称赞',
    '敬佩',
    '感激',
    '和解',
    '原谅',
    '合作',
    '并肩',
    '携手',
    '救下',
    '救活',
    '治愈',
]
# 负面互动词（降低亲密度）
_NEGATIVE_INTERACTION = [
    '争吵',
    '打架',
    '威胁',
    '欺骗',
    '背叛',
    '背叛',
    '出卖',
    '嘲笑',
    '讽刺',
    '羞辱',
    '伤害',
    '攻击',
    '指责',
    '质问',
    '怒视',
    '冷笑',
    '无视',
    '拒绝',
    '驱赶',
    '抛弃',
    '暗杀',
    '陷害',
    '诬陷',
    '陷害',
]
# 中性互动词（建立关系）
_NEUTRAL_INTERACTION = [
    '相遇',
    '结识',
    '初见',
    '交谈',
    '对话',
    '认识',
    '重逢',
    '擦肩',
    '偶遇',
    '介绍',
    '请教',
    '询问',
    '回答',
    '告知',
    '打听',
]


async def _auto_update_relationships(db, chapter_id: str, project_id: str, user_id: str):
    """生成后自动更新关系网：提取角色互动并更新 CharacterRelationship 表。

    优化：使用句子分割 + jieba分词，只检测两角色在同一句子中的互动。
    """
    own_db = None
    try:
        from app.database import get_db_session

        own_db = await get_db_session(user_id)
        from app.models.chapter import Chapter
        from app.models.character import Character
        from app.models.relationship import CharacterRelationship
        from sqlalchemy import select
        import re

        # 获取章节内容
        r = await own_db.execute(select(Chapter).where(Chapter.id == chapter_id))
        chapter = r.scalar_one_or_none()
        if not chapter or not chapter.content:
            return
        content = chapter.content[:50000]
        current_chapter = chapter.chapter_number or 0

        # 获取项目所有角色
        chars_r = await own_db.execute(select(Character).where(Character.project_id == project_id).limit(50))
        chars = chars_r.scalars().all()
        if len(chars) < 2:
            return

        # 角色名 → character_id 映射（支持多字名优先匹配）
        char_map = {}
        for c in chars:
            if c.name:
                char_map[c.name.strip()] = c.id

        # 中文句子分割（按标点）
        sentences = re.split(r'[。！？；\n]+', content)

        updated_count = 0
        for sentence in sentences:
            if len(sentence) < 5:
                continue

            # 找出当前句子中的角色
            chars_in_sentence = []
            for name, cid in char_map.items():
                if name in sentence:
                    chars_in_sentence.append((name, cid))

            if len(chars_in_sentence) < 2:
                continue

            # 检测句子中的互动词
            found_positive = any(w in sentence for w in _POSITIVE_INTERACTION)
            found_negative = any(w in sentence for w in _NEGATIVE_INTERACTION)

            if not found_positive and not found_negative:
                continue

            # 计算亲密度变化
            intimacy_delta = 0
            if found_positive and not found_negative:
                intimacy_delta = +5
            elif found_negative and not found_positive:
                intimacy_delta = -5
            elif found_positive and found_negative:
                intimacy_delta = +2

            # 消除N+1：收集本句所有角色对，批量查询关系
            pair_ids = [(id1, id2) for i, (name1, id1) in enumerate(chars_in_sentence) for name2, id2 in chars_in_sentence[i + 1 :]]
            if not pair_ids:
                continue
            pair_ids_unique = list(set(pair_ids))
            all_from_ids = list(set(p[0] for p in pair_ids_unique))
            all_to_ids = list(set(p[1] for p in pair_ids_unique))
            # 批量查询所有 (from_id, to_id) 组合
            rels_result = await own_db.execute(
                select(CharacterRelationship).where(
                    CharacterRelationship.project_id == project_id,
                    CharacterRelationship.character_from_id.in_(all_from_ids),
                    CharacterRelationship.character_to_id.in_(all_to_ids),
                )
            )
            rels_map = {(r.character_from_id, r.character_to_id): r for r in rels_result.scalars().all()}

            # 为句子中的每对角色创建/更新关系
            for i, (name1, id1) in enumerate(chars_in_sentence):
                for name2, id2 in chars_in_sentence[i + 1 :]:
                    # 消除N+1：从预查字典查找关系记录
                    existing = rels_map.get((id1, id2))

                    if existing:
                        new_level = max(-100, min(100, (existing.intimacy_level or 50) + intimacy_delta))
                        existing.intimacy_level = new_level
                        existing.updated_at = __import__('datetime').datetime.now()
                        logger.info(f'🔗 [PM关系网] 更新: {name1}↔{name2} → {new_level} (第{current_chapter}章)')
                    else:
                        new_rel = CharacterRelationship(
                            id=str(__import__('uuid').uuid4()),
                            project_id=project_id,
                            character_from_id=id1,
                            character_to_id=id2,
                            intimacy_level=max(-100, min(100, 50 + intimacy_delta)),
                            status='active',
                            source='ai',
                        )
                        own_db.add(new_rel)
                        logger.info(f'🔗 [PM关系网] 新建: {name1}↔{name2} = {50 + intimacy_delta} (第{current_chapter}章)')

                    updated_count += 1

        if updated_count > 0:
            await own_db.commit()
            logger.info(f'✅ [PM关系网] 第{current_chapter}章更新 {updated_count} 条关系')

    except Exception as e:
        logger.info(f'[EventBus] _auto_update_relationships failed (非阻塞): {e}')
    finally:
        if own_db:
            try:
                await own_db.close()
            except Exception as e:
                logger.warning(f'[EventBus] db.close 失败: {e}')  # 资源清理失败不扩散
