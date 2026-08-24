"""
维度 E · 百科全书的储备 — 创作知识检索与注入

知识源两级：
1. 种子百科 backend/data/knowledge_seed/*.md（内置写作技法，随项目交付）
2. 用户经验技能库（复用 inspiration_sub.skill_system 的三级检索）

用法：
- search_knowledge(topic, top_k)          — 纯本地关键词检索，无副作用
- get_knowledge_context(user_id, topic, db) — 合成可注入的知识片段（async）
- inject_knowledge(system_prompt, text)    — 把知识片段拼入提示词（未命中原样返回）
"""

import re
from pathlib import Path
from typing import Any, Optional

from app.logger import get_logger

logger = get_logger(__name__)

# backend/app/services/companion/encyclopedia.py
# parents[0]=companion [1]=services [2]=app [3]=backend
_KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / 'data' / 'knowledge_seed'

_knowledge_cache: Optional[dict[str, dict]] = None


# =============================================================================
# 种子百科加载
# =============================================================================
def _parse_frontmatter(text: str) -> Optional[dict]:
    """解析 md front-matter（--- name/description/tags ---）。"""
    if not text.startswith('---'):
        return None
    end = text.find('\n---', 4)
    if end < 0:
        return None
    meta: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        line = line.strip()
        if not line or ':' not in line:
            continue
        key, _, val = line.partition(':')
        key = key.strip()
        val = val.strip().strip('"\'')
        if key in ('tags',):
            val = [t.strip() for t in val.strip('[]').split(',') if t.strip()]
        meta[key] = val
    if not meta.get('name'):
        return None
    return meta


def _strip_frontmatter(text: str) -> str:
    if text.startswith('---'):
        end = text.find('\n---', 4)
        if end >= 0:
            return text[end + 4:].strip()
    return text.strip()


def load_knowledge_entries() -> dict[str, dict]:
    """加载种子百科（懒加载 + 进程内缓存）。"""
    global _knowledge_cache
    if _knowledge_cache is not None:
        return _knowledge_cache
    entries: dict[str, dict] = {}
    if _KNOWLEDGE_DIR.is_dir():
        for f in sorted(_KNOWLEDGE_DIR.glob('*.md')):
            try:
                text = f.read_text(encoding='utf-8')
                meta = _parse_frontmatter(text)
                if meta:
                    meta['body'] = _strip_frontmatter(text)
                    entries[meta['name']] = meta
            except Exception as e:  # noqa: BLE001
                logger.warning('[companion] 知识条目读取失败 %s: %s', f.name, e)
    else:
        logger.warning('[companion] 种子知识目录不存在: %s', _KNOWLEDGE_DIR)
    _knowledge_cache = entries
    return entries


# =============================================================================
# 检索
# =============================================================================
def _tokenize(text: str) -> list[str]:
    return re.findall(r'[\u4e00-\u9fff]{2,6}', text or '')


def _clean_text(text: str) -> str:
    """去掉 markdown 符号，转为平实文本。"""
    text = re.sub(r'[#*`>\-]', '', text or '')
    return re.sub(r'\s+', ' ', text).strip()


def search_knowledge(topic: str, top_k: int = 3) -> list[dict]:
    """关键词打分检索种子百科。"""
    words = set(_tokenize(topic))
    if not words:
        return []
    scored: list[dict] = []
    for name, entry in load_knowledge_entries().items():
        hay = ' '.join([entry.get('description', ''), ' '.join(entry.get('tags', [])), name])
        hay_words = set(_tokenize(hay))
        if not hay_words:
            continue
        score = len(words & hay_words) / max(len(words), len(hay_words))
        if score > 0.05:
            scored.append(
                {
                    'name': name,
                    'description': entry.get('description', ''),
                    'tags': entry.get('tags', []),
                    'body': entry.get('body', ''),
                    'score': round(score, 3),
                }
            )
    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:top_k]


async def get_knowledge_context(user_id: str, topic: str, db=None) -> str:
    """合成可注入的知识片段（种子百科 + 用户经验技能库）。

    Args:
        user_id: 用户 ID
        topic: 当前创作主题/场景描述
        db: 可选 AsyncSession（用于技能库 hit_count 与向量检索）

    Returns:
        知识片段文本；无任何命中时返回空串。
    """
    parts: list[str] = []
    for hit in search_knowledge(topic, top_k=2):
        body = _clean_text(hit.get('body', ''))[:260]
        parts.append(f'【创作百科·{hit["name"]}】{body}')

    # 复用灵感技能库（全局 + 用户私有，向量/关键词三级检索）
    try:
        from app.services.inspiration_sub.skill_system import InspirationSkillSystem

        skill = await InspirationSkillSystem.find_matching_skill(user_id, topic, db)
        if skill and len(skill) > 20:
            parts.append(f'【过往经验】{skill[:400].replace(chr(10), " ")}')
    except Exception as e:  # noqa: BLE001
        logger.warning('[companion] 技能库检索失败(降级跳过): %s', e)

    return '\n'.join(parts)


def inject_knowledge(system_prompt: str, knowledge_text: str) -> str:
    """把知识片段拼入 system_prompt；无知识时原样返回。"""
    if not knowledge_text:
        return system_prompt
    from app.services.companion import prompts

    block = prompts.render('knowledge_inject', knowledge=knowledge_text)
    return f'{system_prompt}\n\n{block}' if system_prompt else block
