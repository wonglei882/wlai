"""
companion 陪伴中枢 —「苏格拉底 · 家教 · 百科全书 · 秘书」四维能力门面

模块划分：
- socratic     维度 S：引导式提问，不直接给答案（含巡检链路拦截入口）
- tutor        维度 T：因材施教的分层反馈与鼓励
- encyclopedia 维度 E：创作知识检索与注入（种子百科 + 经验技能库）
- secretary    维度 P：主动关怀话术（问候 / 简报 / 里程碑 / 低打扰提醒）
- prompts      提示词模板库（补齐提示词工坊模板层缺口）

设计约束：
- 本包不顶层 import 任何 pm_* 核心模块；核心模块仅在函数内懒导入本包，
  从根上避免循环依赖。
- 所有对外能力均带异常兜底：任何失败只记日志，不影响 PM 主链路。
"""

from app.services.companion.encyclopedia import (
    get_knowledge_context,
    inject_knowledge,
    load_knowledge_entries,
    search_knowledge,
)
from app.services.companion.socratic import (
    build_socratic_chain,
    generate_socratic_reply,
    resolve_chain,
    should_guide,
    socratic_redirect_if_needed,
)
from app.services.companion.tutor import (
    attempt_tier,
    compose_encouragement,
    detect_experience_level,
    format_tutored_feedback,
)
from app.services.companion.secretary import (
    compose_daily_briefing,
    compose_gentle_reminder,
    compose_milestone_message,
    personal_greeting,
)
from app.services.companion import prompts

__all__ = [
    # S 苏格拉底
    'socratic_redirect_if_needed',
    'build_socratic_chain',
    'generate_socratic_reply',
    'should_guide',
    'resolve_chain',
    # T 家教
    'detect_experience_level',
    'format_tutored_feedback',
    'attempt_tier',
    'compose_encouragement',
    # E 百科
    'get_knowledge_context',
    'search_knowledge',
    'inject_knowledge',
    'load_knowledge_entries',
    # P 秘书
    'compose_daily_briefing',
    'compose_milestone_message',
    'compose_gentle_reminder',
    'personal_greeting',
    # 提示词模板
    'prompts',
]
