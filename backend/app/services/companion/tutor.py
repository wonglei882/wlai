"""
维度 T · 优秀家教的耐心 — 因材施教的分层反馈

分层递进规则：
- 首次犯错 → 讲「原则」：说清楚为什么，给出判断标准
- 再次犯错 → 给「线索」：给方向，不给答案
- 三次以上 → 给「示例」：最小可仿写样例，鼓励举一反三

按用户水平（PMUserProfile.experience_level）调整语气与详略。
"""

from datetime import datetime

from app.logger import get_logger

logger = get_logger(__name__)

VALID_LEVELS = ('beginner', 'intermediate', 'expert')

_TONE_BY_LEVEL = {
    'beginner': '温和耐心，多鼓励，少术语',
    'intermediate': '亲切专业，给框架，留空间',
    'expert': '平等简洁，直击要点',
}

_TIER_INFO = {
    'principle': {
        'label': '我们先看看为什么会这样',
        'advice': '讲清原则与判断标准，不直接动手改',
    },
    'hint': {
        'label': '再想想，我给你点线索',
        'advice': '给方向性线索，引导自己发现',
    },
    'example': {
        'label': '我们一起看个例子',
        'advice': '给最小可仿写示例，鼓励举一反三',
    },
}

_STEPS_BY_TIER = {
    'principle': [
        '复述问题现象，确认没有误解',
        '解释背后的创作原则（为什么这是个问题）',
        '给出一条自查清单，让作者自己核对',
    ],
    'hint': [
        '提示相关维度（结构 / 情感 / 逻辑 / 语言）',
        '请作者定位最「别扭」的那一句或那一拍',
        '约定一个轻量验证方式（读出声 / 隔天回看）',
    ],
    'example': [
        '给一段 2~3 句的最小示范',
        '对比示范与原文的差异点',
        '请作者基于自己的故事改一版',
    ],
}

_ENC_POOL = {
    'fix_success': [
        '这次处理得很稳，你其实已经摸到窍门了。',
        '改得不错，这就是手感积累的过程。',
        '很好，这个问题到此为止，我们继续。',
    ],
    'guidance': [
        '别急，想清楚再动手，答案往往在你心里。',
        '每个好作者都是这样一步步想明白的。',
        '你已经看到关键了，再往前一小步就是答案。',
    ],
    'milestone': [
        '这一程走得不容易，你配得上这个进度。',
        '里程碑达成，记得给自己一点肯定。',
        '故事在长大，你也在长大。',
    ],
}


# =============================================================================
# 水平检测
# =============================================================================
def detect_experience_level(profile) -> str:
    """从用户画像读取水平等级；无画像 / 异常兜底 beginner。"""
    if profile is None:
        return 'beginner'
    try:
        level = (profile.experience_level or 'beginner').lower()
    except AttributeError:
        return 'beginner'
    return level if level in VALID_LEVELS else 'beginner'


# =============================================================================
# 分层反馈
# =============================================================================
def attempt_tier(attempt_count: int) -> str:
    """按同类错误次数决定反馈层级（principle → hint → example）。"""
    try:
        n = max(1, int(attempt_count))
    except (TypeError, ValueError):
        n = 1
    if n <= 1:
        return 'principle'
    if n <= 2:
        return 'hint'
    return 'example'


def format_tutored_feedback(
    issue: dict,
    experience_level: str = 'beginner',
    attempt_count: int = 1,
    detail_pref: str = 'medium',
) -> dict:
    """生成分层家教反馈。

    Args:
        issue: 问题字典（type / message / severity）
        experience_level: beginner / intermediate / expert
        attempt_count: 同类错误已发生次数
        detail_pref: high / medium / low（PMUserProfile.preferred_detail_level）

    Returns:
        dict: {tier, tier_label, tone, summary, advice, steps, example, encouragement}
    """
    if experience_level not in VALID_LEVELS:
        experience_level = 'beginner'
    tier = attempt_tier(attempt_count)

    brief = (issue.get('message') or issue.get('type') or '创作问题')
    if len(brief) > 80:
        brief = brief[:77] + '…'

    steps = _STEPS_BY_TIER[tier]
    # 低详略偏好时压缩步骤
    if detail_pref == 'low':
        steps = steps[:2]

    return {
        'tier': tier,
        'tier_label': _TIER_INFO[tier]['label'],
        'tone': _TONE_BY_LEVEL[experience_level],
        'summary': f'关于「{brief}」',
        'advice': _TIER_INFO[tier]['advice'],
        'steps': steps,
        'example': _make_example(issue, tier),
        'encouragement': compose_encouragement('guidance', experience_level),
    }


def _make_example(issue: dict, tier: str) -> str:
    """示例层才返回示范文本；其余层级返回空串（不给答案）。"""
    if tier != 'example':
        return ''
    itype = issue.get('type', '')
    hint = {
        'character_location_jump': '补一拍过渡：先交代离开，再交代抵达，中间留一行感受。',
        'dialogue_quality': '把「他很生气地说……吗？」改成动作+短句：他捏紧杯沿，一字一字地说：「……」。',
        'pacing': '在长句堆里插一个单句段落，让读者有呼吸的缝隙。',
    }.get(itype, '示范：把这个念头用最直白的一句话写出来，再决定保留还是修剪。')
    return hint


# =============================================================================
# 鼓励话术
# =============================================================================
def compose_encouragement(kind: str = 'fix_success', experience_level: str = 'beginner') -> str:
    """按场景与水平挑选鼓励语。"""
    pool = _ENC_POOL.get(kind, _ENC_POOL['guidance'])
    idx = 0 if experience_level == 'beginner' else (1 if experience_level == 'intermediate' else 2)
    return pool[idx % len(pool)]


def compose_milestone_message(milestone: str = '') -> str:
    """里程碑祝贺（配合 secretary 使用）。"""
    base = _ENC_POOL['milestone'][1]
    return f'🎉 {milestone or "里程碑达成"}！{base}'
