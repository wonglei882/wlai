"""PM 写操作工具集 — Facade（向后兼容重导出层）。

由 pm_write_operations.py 拆分而来（god file 专项重构）。
原始1131行文件拆分为5个模块：
  pm_write_base      — 共享 imports + _make_response
  pm_write_crud      — CRUD 操作（update/delete）
  pm_write_generate  — AI 生成操作（volume/pacing/conflict/chapter）
  pm_write_handlers  — Handler 包装 + ToolRegistry 注册
  pm_write_diagnose  — 诊断增强（pm_diagnose_project / pm_analyze_relationships）

本 facade 文件保留原有 import 路径的向后兼容。
建议新代码直接导入子模块。
"""

# Re-export: 共享工具

# Re-export: CRUD 操作

# Re-export: AI 生成操作

# Re-export: Handler 包装 + 注册
from app.agent.domain.tools.pm_write_handlers import (
    handle_update_outline,
    handle_update_body,
    handle_update_chapter_context,
    handle_update_character,
    handle_update_character_state,
    handle_delete_chapter,
    handle_delete_foreshadow,
    handle_delete_subplot,
    handle_generate_volume_outlines,
    handle_generate_pacing,
    handle_suggest_conflict,
    handle_diagnose_project,
    handle_analyze_relationships,
    handle_create_chapter_with_plan,
    register_pm_write_operations,  # noqa: F401  (re-export; used by register.py)
    _register_p2_tools,  # noqa: F401  (re-export; used by register.py)
)

# 兼容旧名（_handle_* → handle_* 迁移期别名）
_handle_update_outline = handle_update_outline
_handle_update_body = handle_update_body
_handle_update_chapter_context = handle_update_chapter_context
_handle_update_character = handle_update_character
_handle_update_character_state = handle_update_character_state
_handle_delete_chapter = handle_delete_chapter
_handle_delete_foreshadow = handle_delete_foreshadow
_handle_delete_subplot = handle_delete_subplot
_handle_generate_volume_outlines = handle_generate_volume_outlines
_handle_generate_pacing = handle_generate_pacing
_handle_suggest_conflict = handle_suggest_conflict
_handle_diagnose_project = handle_diagnose_project
_handle_analyze_relationships = handle_analyze_relationships
_handle_create_chapter_with_plan = handle_create_chapter_with_plan

# Re-export: 诊断增强
