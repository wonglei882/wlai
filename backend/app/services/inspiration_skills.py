"""
灵感模式·技能自生长系统（旧路径兼容转发层）

历史：inspiration_skills 曾为单模块；P3 重构拆分为 inspiration_sub 子包后，
以下旧调用方仍使用本路径（懒导入，功能触发时才生效）：
- pm_sequence.py:   _search_skills_by_context / InspirationSkillSystem / _upsert_skill_embedding
- pm_consistency.py: _resolve_diagnostic_log
- event_bus_listeners.py: auto_skill_from_tool_result

本文件仅做符号转发，不承载业务逻辑。
新代码请直接导入 app.services.inspiration_sub.*。
"""

from app.services.inspiration_sub.auto_skill import auto_skill_from_tool_result
from app.services.inspiration_sub.diagnostic import (
    _resolve_diagnostic_log,
    _search_skills_by_context,
    _upsert_diagnostic_log,
)
from app.services.inspiration_sub.skill_system import (
    InspirationSkillSystem,
    _upsert_skill_embedding,
)

__all__ = [
    'auto_skill_from_tool_result',
    '_search_skills_by_context',
    '_resolve_diagnostic_log',
    '_upsert_diagnostic_log',
    'InspirationSkillSystem',
    '_upsert_skill_embedding',
]
