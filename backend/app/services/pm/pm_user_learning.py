"""画像学习 — 从决策结果反哺 PMUserProfile（L4 经验进化）。

规则：
- 修复验证通过 → 对应技能记入 skills_mastered（防膨胀），水平计数 intermediate+1
- 修复失败/部分成功 → 水平计数 beginner+1
- 每 recompute_every 次决策按加权占比重算 experience_level（最小样本防抖动）

所有操作非阻塞：失败仅日志，不破坏主决策链路。
"""

import logging

from sqlalchemy import select

from app.models.pm_user_profile import PMUserProfile

logger = logging.getLogger(__name__)

_SKILL_MAP = {
    'pm_agent_foreshadow_stale': '伏笔管理',
    'foreshadow_stale': '伏笔管理',
    'pm_agent_world_drift': '世界观一致性',
    'world_rule_drift': '世界观一致性',
    'pm_agent_character_jump': '角色行动逻辑',
    'character_location_jump': '角色行动逻辑',
    'pm_agent_outline_drift': '大纲把控',
    'outline_drift': '大纲把控',
    'pm_agent_paragraph_too_long': '段落节奏',
    'pm_agent_quality_score_low': '整体质量',
}
_SKILL_CAP = 20
RECOMPUTE_EVERY = 20   # 每 N 次决策重算一次水平
_MIN_SAMPLES = 5        # 最少样本数，防抖动


async def learn_from_decision(db, user_id: str, diag_type: str, fix_result: str, verified: bool) -> bool:
    """根据一次决策结果学习。返回是否成功。"""
    try:
        if not user_id:
            return False
        profile = (
            await db.execute(select(PMUserProfile).where(PMUserProfile.user_id == user_id).limit(1))
        ).scalar_one_or_none()
        if profile is None:
            profile = PMUserProfile(user_id=user_id, experience_level='beginner')
            db.add(profile)
        counters = dict(profile.question_type_counts or {})
        if fix_result == 'success' and verified:
            skill = _SKILL_MAP.get(diag_type)
            if skill:
                skills = list(profile.skills_mastered or [])
                if skill not in skills:
                    skills.append(skill)
                    profile.skills_mastered = skills[:_SKILL_CAP]
            counters['intermediate'] = (counters.get('intermediate') or 0) + 1
        elif fix_result in ('failed', 'partial'):
            counters['beginner'] = (counters.get('beginner') or 0) + 1
        profile.question_type_counts = counters
        total = sum(counters.values())
        if total >= _MIN_SAMPLES and total % RECOMPUTE_EVERY == 0:
            new_level = _recompute_level(counters, total)
            if new_level != profile.experience_level:
                logger.info('[PM-Learning] 经验水平 %s -> %s (user=%s)', profile.experience_level, new_level, user_id)
                profile.experience_level = new_level
        await db.commit()
        return True
    except Exception as e:  # noqa: BLE001
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning('[PM-Learning] 学习失败（非阻塞）: %s', e)
        return False


def _recompute_level(counters: dict, total: int) -> str:
    """加权占比重估：expert*3 / intermediate*2 / beginner*1。"""
    expert = counters.get('expert') or 0
    inter = counters.get('intermediate') or 0
    beg = counters.get('beginner') or 0
    total_w = expert * 3 + inter * 2 + beg
    if total_w <= 0:
        return 'beginner'
    expert_ratio = (expert * 3) / total_w
    beg_ratio = beg / total_w
    if expert_ratio >= 0.5 and expert >= 3:
        return 'expert'
    if beg_ratio >= 0.6:
        return 'beginner'
    return 'intermediate'
