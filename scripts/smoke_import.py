"""Smoke-test: try to import PM core modules to verify dependency completeness."""
import importlib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

MODULES = [
    "app.services.pm.feature_config",
    "app.services.pm.pm_ai_client",
    "app.services.pm.pm_llm_guard",
    "app.services.pm.pm_token_budget",
    "app.services.pm.pm_guardian_models",
    "app.services.pm.pm_guardian_health",
    "app.services.pm.scan_support",
    "app.services.pm.memory",
    "app.services.pm.quality_scorer",
    "app.services.pm.pm_preference_learner",
    "app.services.pm.self_tuning",
    "app.services.pm.self_tuning_strategy",
    "app.services.pm.self_evolve",
    "app.services.pm.pm_scanners",
    "app.services.pm.pm_fix_handlers",
    "app.services.pm.pm_fix_executors",
    "app.services.pm.pm_decision_state",
    "app.services.pm.pm_decision_helpers",
    "app.services.pm.pm_decision_verify",
    "app.services.pm.pm_decision_policy",
    "app.services.pm.pm_metrics",
    "app.services.pm.pm_consistency_guardian",
    "app.services.pm.pm_agent_decision",
    "app.services.pm.pm_agent",
    "app.services.pm.dims.base",
    "app.services.pm.dims.quality_score",
    "app.services.pm.dims.paragraph_format",
]

ok, fail = [], []
for m in MODULES:
    try:
        importlib.import_module(m)
        ok.append(m)
    except Exception as e:
        fail.append((m, f"{type(e).__name__}: {e}"))

print(f"OK   ({len(ok)}/{len(MODULES)}):")
for m in ok:
    print(f"  [OK] {m}")
print(f"\nFAIL ({len(fail)}/{len(MODULES)}):")
for m, e in fail:
    print(f"  [FAIL] {m}\n    -> {e}")
