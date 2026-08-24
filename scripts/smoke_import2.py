"""Smoke-test round 2: AI chain + agent tools + models + api."""
import importlib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

MODULES = [
    "app.config",
    "app.logger",
    "app.database",
    "app.models.base",
    "app.models.pm_decision_log",
    "app.models.pm_v2",
    "app.models.pm_consistency_state",
    "app.models.mistake_log",
    "app.models.skill",
    "app.services.json_helper",
    "app.services.ai.ai_service",
    "app.services.ai.ai_config",
    "app.services.ai.ai_metrics",
    "app.agent.core.command_registry",
    "app.agent.domain.tools.pm_consistency",
    "app.agent.domain.tools.pm_sequence",
    "app.agent.domain.odd_config",
    "app.api.pm",
    "app.api.pm_control",
    "app.api.pm_diagnostic_logs",
    "app.api.pm_token_usage",
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
