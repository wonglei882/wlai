"""Analyze how each missing module is referenced: top-level (module scope) vs lazy (inside functions)."""
import ast
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "backend")
ROOT = os.path.abspath(ROOT)

MISSING = {
    "app.agent.core.command_executor",
    "app.agent.domain.commands",
    "app.agent.domain.register",
    "app.agent.infrastructure.progress_analyzer",
    "app.agent.infrastructure.text_analysis",
    "app.api.chapters.generate_analysis",
    "app.api.settings",
    "app.core",
    "app.mcp",
    "app.models.analysis_task",
    "app.models.base",
    "app.models.narrative_structure",
    "app.models.ooc_violation",
    "app.models.relationship",
    "app.schemas.foreshadow",
    "app.schemas.outline_structure",
    "app.services.core.mcp_tools_loader",
    "app.services.guardian.continuity_service",
    "app.services.guardian.foreshadow_service",
    "app.services.guardian.ooc_detector",
    "app.services.inspiration_skills",
    "app.services.inspiration_sub.skill_system",
    "app.services.project_manager_service",
    "app.services.quality_forecast",
    "app.utils.redis_client",
}

refs = {}


def is_lazy(node):
    """Walk up parents; if any is a function definition -> the import is lazy."""
    cur = node
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return True
        cur = getattr(cur, "parent", None)
    return False


def attach_parents(tree):
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent


for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "app")):
    if "__pycache__" in dirpath:
        continue
    for f in files:
        if not f.endswith(".py"):
            continue
        p = os.path.join(dirpath, f)
        rel_file = os.path.relpath(p, ROOT)
        try:
            tree = ast.parse(open(p, encoding="utf-8").read())
        except Exception:
            continue
        attach_parents(tree)
        for node in ast.walk(tree):
            mod = None
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
                mod = node.module
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("app"):
                        refs.setdefault(a.name, set()).add((rel_file, is_lazy(node)))
                continue
            if mod:
                refs.setdefault(mod, set()).add((rel_file, is_lazy(node)))

print("=" * 90)
for m in sorted(MISSING):
    r = refs.get(m, set())
    top = sorted({x for x, lazy in r if not lazy})
    laz = sorted({x for x, lazy in r if lazy})
    print(f"[{m}]")
    print(f"  TOP-LEVEL (required): {top if top else 'NONE'}")
    print(f"  lazy (optional)     : {laz if laz else 'NONE'}")
