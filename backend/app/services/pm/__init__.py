"""
services/pm — 项目主管 Agent
核心差异化能力，所有主动预警、自进化、质量评估
"""

# ---------------------------------------------------------------------------
# Phase 2 后文件已迁入 services/pm/。旧 try/except ImportError 兜底已清理。
# ---------------------------------------------------------------------------
from app.services.pm.memory import PMMemoryV2 as PMMemory  # noqa: F401
from app.services.pm.quality_scorer import PMQualityScorerV2 as PMQualityScorer  # noqa: F401
from app.services.pm.pm_consistency_guardian import PMConsistencyGuardian  # noqa: F401
from app.services.pm.self_evolve import SelfCritique  # noqa: F401
from app.services.pm.self_tuning import record_success, record_failure  # noqa: F401
from app.services.proactive_reporter import ProactiveReporter  # noqa: F401
from app.services.proactive_suggestions import generate_proactive_suggestions  # noqa: F401
