"""
维度 P · 私人秘书的贴心 — 主动关怀与个性化简报

能力：
- personal_greeting(hour)          按时段问候
- compose_daily_briefing(...)      定制化每日创作简报
- compose_milestone_message(...)   里程碑祝贺
- compose_gentle_reminder(...)     对遗留问题的低打扰提醒
"""

from datetime import datetime
from typing import Any, Optional

import logging

logger = logging.getLogger(__name__)

_GREETING = {
    'morning': '早上好，新的一天，从笔下开始吧。',
    'noon': '午间好，写了几段也记得让眼睛歇一歇。',
    'evening': '晚上好，你的故事还在等着你。',
    'night': '夜深了，写到刚好就睡吧，灵感明天还会来。',
}

_TONE_NAMES = {'formal': '正式克制', 'casual': '轻松自然', 'warm': '温暖亲切'}
# PMUserProfile.preferred_detail_level → 语气（话多/暖 ↔ 话少/克制）
_DETAIL_TO_TONE = {'high': 'warm', 'medium': 'casual', 'low': 'formal'}

_TIPS = [
    '写不动的时候，把最难写的那段朗读出来。',
    '对话卡壳时，先写「TA 想得到什么」，再写台词。',
    '一章写完先别改，隔一天再看，你会看见读者看不见的缝隙。',
    '角色要「听」对方说话，而不是各自独白。',
    '进度不是字数，是「这一章解决了什么」。',
]


# =============================================================================
# 问候
# =============================================================================
def _greet_key(hour: int) -> str:
    if 5 <= hour < 11:
        return 'morning'
    if 11 <= hour < 13:
        return 'noon'
    if 13 <= hour < 19:
        return 'evening'
    return 'night'


def personal_greeting(hour: Optional[int] = None) -> str:
    """按时段返回问候语。"""
    if hour is None:
        hour = datetime.now().hour
    return _GREETING.get(_greet_key(hour), _GREETING['evening'])


# =============================================================================
# 简报
# =============================================================================
def _pick_tip(topic: str = '') -> str:
    """抽一条创作小贴士（优先结合百科知识，失败回退内置）。"""
    try:
        from app.services.companion.encyclopedia import search_knowledge

        hits = search_knowledge(topic, top_k=1) if topic else []
        if hits:
            from app.services.companion.encyclopedia import _clean_text

            body = _clean_text(hits[0].get('body', ''))[:80]
            if body:
                return body
    except Exception as e:  # noqa: BLE001
        logger.debug('[companion] 小贴士检索失败，用内置: %s', e)
    # 按小时轮换，避免每天同一句
    return _TIPS[datetime.now().hour % len(_TIPS)] if _TIPS else '记得休息。'


def _tone_for(profile: Any) -> str:
    """根据用户画像的详细度偏好映射语气。"""
    pref = 'medium'
    try:
        pref = (profile.preferred_detail_level or 'medium')
    except AttributeError:
        pass
    tone_key = _DETAIL_TO_TONE.get(pref, 'casual')
    return _TONE_NAMES.get(tone_key, _TONE_NAMES['casual'])


def compose_daily_briefing(
    project_ctx: Optional[dict] = None,
    report: Optional[dict] = None,
    profile: Any = None,
) -> dict:
    """生成每日创作简报。

    Args:
        project_ctx: 项目上下文（title / chapter_count / progress）
        report:      proactive_reporter 的报告 dict（issues / summary 等）
        profile:     PMUserProfile（语气与称呼）

    Returns:
        dict: {greeting, tone, progress_lines, reminders, tips, signoff, text}
    """
    ctx = project_ctx or {}
    rep = report or {}

    # 进展
    progress_lines = []
    title = ctx.get('title') or '你的故事'
    chapter_count = ctx.get('chapter_count')
    progress = ctx.get('progress')
    if chapter_count is not None:
        progress_lines.append(f'目前写到第 {chapter_count} 章')
    if progress is not None:
        progress_lines.append(f'整体进度 {progress}')
    if not progress_lines:
        progress_lines.append(f'《{title}》还在生长中')

    # 提醒（未解决问题）
    reminders = []
    issues = rep.get('issues') or rep.get('unresolved_issues') or []
    for it in issues[:3]:
        msg = (it.get('message') or it.get('type') or '创作问题')
        if len(msg) > 40:
            msg = msg[:37] + '…'
        reminders.append(msg)
    if not reminders:
        reminders.append('今天没有需要担心的遗留问题。')

    # 小贴士
    topic = ctx.get('last_topic') or ctx.get('title') or ''
    tips = _pick_tip(topic)

    greeting = personal_greeting()
    tone = _tone_for(profile)
    encouragement = '晚安，明天见。' if _greet_key(datetime.now().hour) == 'night' else '继续写下去，你会越来越像你笔下的主角。'

    text = f'{greeting} 《{title}》今日简报：'
    text += '；'.join(progress_lines[:2]) + '。'
    if reminders and '没有需要担心' not in reminders[0]:
        text += '有几点可以看看：' + '；'.join(reminders[:2]) + '。'
    text += f'小贴士：{tips}。{encouragement}'

    return {
        'greeting': greeting,
        'tone': tone,
        'progress_lines': progress_lines,
        'reminders': reminders,
        'tips': tips,
        'signoff': encouragement,
        'text': text,
    }


def compose_milestone_message(project_ctx: Optional[dict] = None, milestone: str = '') -> str:
    """里程碑祝贺。"""
    ctx = project_ctx or {}
    title = ctx.get('title') or ''
    prefix = f'《{title}》' if title else ''
    try:
        from app.services.companion.tutor import compose_encouragement

        base = compose_encouragement('milestone')
    except Exception:  # noqa: BLE001
        base = '里程碑达成，记得给自己一点肯定。'
    return f'{prefix}{milestone or "里程碑达成"}！{base}'


def compose_gentle_reminder(issue: dict, profile: Any = None) -> str:
    """对遗留问题的低打扰提醒（语气随用户偏好）。"""
    msg = (issue.get('message') or issue.get('type') or '那个创作问题')
    if len(msg) > 40:
        msg = msg[:37] + '…'
    tone = _tone_for(profile)
    if tone == _TONE_NAMES['formal']:
        return f'有一项待处理：「{msg}」。方便时看一下即可。'
    return f'有件事不急，等你有空时看看就好——「{msg}」。'
