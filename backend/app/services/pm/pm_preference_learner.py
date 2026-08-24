"""PM Agent 用户偏好学习 — 从用户反馈/编辑中提取偏好，存入 UserPreference 表。

来源：
1. 用户在 PM Agent 回复后的反馈（thumbs up/down）
2. 用户对生成章节的编辑行为
3. PM Agent 的决策调整记录

注入：
- build_project_context 在构建 PM Agent 上下文时调用，偏好作为额外背景注入。
"""

import logging
from typing import Any
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pm_v2 import UserPreference

logger = logging.getLogger(__name__)

# 偏好类型 → 关键词映射
PREFERENCE_KEYWORDS = {
    'pacing': ['节奏', '太快', '太慢', '节奏感', '铺垫', '高潮', '推进'],
    'dialogue': ['对话', '描写', '内心戏', '独白', '对白', '心理描写'],
    'description': ['细节', '描写', '环境', '场景', '外貌', '动作'],
    'tone': ['文风', '风格', '轻松', '严肃', '幽默', '压抑'],
    'length': ['太长', '太短', '字数', '篇幅', '精简', '详细'],
}


class PreferenceBelief:
    """偏好置信度：用 Beta(α, β) 建模，正反馈+α，负反馈+β。

    替代旧的 confidence×1.1 / confidence+0.1 硬更新。
    少量反馈时置信度低（不确定性高），随样本量增加趋于稳定。
    """

    def __init__(self, alpha: float = 1.0, beta: float = 1.0):
        self.alpha = alpha
        self.beta = beta

    def update(self, positive: bool, weight: float = 1.0) -> None:
        if positive:
            self.alpha += weight
        else:
            self.beta += weight

    @property
    def confidence(self) -> float:
        """期望值 = α/(α+β)"""
        total = self.alpha + self.beta
        return self.alpha / total if total > 0 else 0.5

    @property
    def sample_size(self) -> float:
        return self.alpha + self.beta

    @property
    def json(self) -> dict:
        return {'alpha': self.alpha, 'beta': self.beta}

    @classmethod
    def from_json(cls, data: dict) -> 'PreferenceBelief':
        return cls(alpha=data.get('alpha', 1.0), beta=data.get('beta', 1.0))


async def learn_from_feedback(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    feedback_type: str,  # "thumbs_up" | "thumbs_down" | "edit"
    content: str,
    context: str = '',
) -> str | None:
    """从用户反馈中学习偏好，存入 UserPreference 表。

    分析 feedback_content，识别偏好类型，更新置信度。
    """
    try:
        content_lower = content.lower()
        matched_types = []

        for pref_type, keywords in PREFERENCE_KEYWORDS.items():
            for kw in keywords:
                if kw in content_lower or kw in content:
                    matched_types.append(pref_type)
                    break

        if not matched_types:
            # 默认标记为 general feedback
            matched_types = ['general']

        pref_id = None
        for pref_type in matched_types:
            pref = await _upsert_preference(db, user_id, project_id, pref_type, content, feedback_type)
            if pref and not pref_id:
                pref_id = pref

        if matched_types:
            logger.info(f'[偏好学习] user={user_id[:8]} project={project_id[:8]} types={matched_types} source={feedback_type}')

        return pref_id

    except Exception as e:
        logger.warning(f'[偏好学习] 学习失败: {e}')
        return None


async def _upsert_preference(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    preference_type: str,
    content: str,
    source: str,
) -> str | None:
    """upsert 用户偏好记录。"""
    # 查找现有同类型偏好
    result = await db.execute(
        select(UserPreference).where(
            and_(
                UserPreference.user_id == user_id,
                UserPreference.project_id == project_id,
                UserPreference.preference_type == preference_type,
            )
        )
    )
    existing = result.scalar_one_or_none()

    # 提取偏好值
    value = _extract_value(content, preference_type)

    # 计算新置信度（Beta 贝叶斯更新）
    if existing:
        belief = PreferenceBelief.from_json(existing.value or {})
        # 根据反馈类型推断正/负反馈（thumbs_up=正，thumbs_down=负，edit=中性偏正）
        # 注：调用方将 feedback_type 按位置传入 source 形参，此处以 source 为准
        positive = source in ('thumbs_up', 'edit')
        belief.update(positive=positive, weight=1.0)
        existing.value = {**(existing.value or {}), **belief.json}
        existing.confidence = belief.confidence
        existing.source = source
        pref_id = existing.id
        logger.info(f'[偏好] 更新已有偏好 type={preference_type} conf={belief.confidence:.2f} (α={belief.alpha:.0f} β={belief.beta:.0f})')
    else:
        new_pref = UserPreference(
            id=_gen_id(),
            user_id=user_id,
            project_id=project_id,
            preference_type=preference_type,
            value=value,
            confidence=0.6,
            source=source,
        )
        db.add(new_pref)
        pref_id = new_pref.id
        logger.info(f'[偏好] 新增偏好 type={preference_type} conf=0.6')

    await db.commit()
    return pref_id


def _extract_value(content: str, preference_type: str) -> dict[str, Any]:
    """从反馈内容中提取偏好值。"""
    base = {
        'content': content[:200],
        'keywords': _extract_keywords(content),
    }

    # 类型特定提取
    if preference_type == 'pacing':
        if '太快' in content or '太赶' in content:
            base['preference'] = 'slower_pacing'
        elif '太慢' in content or '拖沓' in content:
            base['preference'] = 'faster_pacing'
        else:
            base['preference'] = 'balanced_pacing'
    elif preference_type == 'dialogue':
        if '太少' in content or '不够' in content:
            base['preference'] = 'more_dialogue'
        elif '太多' in content:
            base['preference'] = 'less_dialogue'
    elif preference_type == 'description':
        if '太简' in content or '太糙' in content:
            base['preference'] = 'more_detail'
        elif '太繁' in content or '太啰嗦' in content:
            base['preference'] = 'less_detail'

    return base


def _extract_keywords(content: str) -> list[str]:
    """从内容中提取关键词。"""
    # 简单分词 + 过滤
    import jieba

    words = jieba.cut(content)
    return [w for w in words if len(w) >= 2][:10]


def _gen_id() -> str:
    import uuid

    return str(uuid.uuid4())


async def load_user_preferences(
    db: AsyncSession,
    user_id: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """加载用户偏好（高置信度）用于注入上下文。"""
    try:
        result = await db.execute(
            select(UserPreference)
            .where(
                and_(
                    UserPreference.user_id == user_id,
                    UserPreference.project_id == project_id,
                    UserPreference.confidence >= 0.6,
                    UserPreference.preference_type != 'general',
                )
            )
            .order_by(UserPreference.confidence.desc())
        )
        prefs = result.scalars().all()

        return [
            {
                'type': p.preference_type,
                'value': p.value,
                'confidence': p.confidence,
                'source': p.source,
            }
            for p in prefs
        ]
    except Exception as e:
        logger.warning(f'[偏好] 加载失败: {e}')
        return []


def format_preferences_for_context(prefs: list[dict[str, Any]]) -> str:
    """将偏好列表格式化为 PM Agent 上下文字符串。"""
    if not prefs:
        return ''

    lines = ['\n\n## 用户写作偏好（来自历史反馈）']
    for p in prefs[:5]:  # 最多 5 条
        pref_type = p.get('type', '')
        value = p.get('value', {})
        conf = p.get('confidence', 0)
        pref_desc = value.get('preference', value.get('content', '')[:50])

        type_map = {
            'pacing': '节奏',
            'dialogue': '对话',
            'description': '描写',
            'tone': '文风',
            'length': '篇幅',
        }
        type_cn = type_map.get(pref_type, pref_type)

        lines.append(f'- [{type_cn}] {pref_desc}（置信度 {conf:.0%}）')

    return '\n'.join(lines)
