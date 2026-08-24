"""Check that all `from app.X import ...` references in the copied project resolve to existing modules."""
import ast
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "backend")
ROOT = os.path.abspath(ROOT)

# 1. collect all existing modules under backend/app
existing = set()
for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "app")):
    if "__pycache__" in dirpath:
        continue
    rel = os.path.relpath(dirpath, ROOT).replace(os.sep, ".")
    for f in files:
        if f.endswith(".py"):
            mod = f"{rel}.{f[:-3]}" if rel != "." else f[:-3]
            existing.add(mod)
# strip __init__ suffix: app.services.pm.dims -> also app.services.pm.dims.__init__? we treat package itself
# a package module `app.services.pm.dims` is importable even if only __init__.py exists
pkgs = set()
for m in list(existing):
    if m.endswith(".__init__"):
        pkgs.add(m[: -len(".__init__")])
existing |= pkgs

missing = set()
imported_all = set()
for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "app")):
    if "__pycache__" in dirpath:
        continue
    for f in files:
        if not f.endswith(".py"):
            continue
        p = os.path.join(dirpath, f)
        try:
            src = open(p, encoding="utf-8").read()
            tree = ast.parse(src)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
                imported_all.add(node.module)
                if node.module not in existing:
                    missing.add(node.module)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("app"):
                        imported_all.add(a.name)
                        if a.name not in existing:
                            missing.add(a.name)

print(f"IMPORTED_APP_MODULES: {len(imported_all)}")
print(f"MISSING_MODULES: {len(missing)}")
for m in sorted(missing):
    print(f"  MISSING: {m}")
