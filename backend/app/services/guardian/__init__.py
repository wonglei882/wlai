"""
services/guardian — 长篇守护系统
伏笔、因果链、OOC、连续性、高频词 — 生成前主动预警
"""

try:
    from app.services.guardian.long_novel_guardian import LongNovelGuardian, GuardianReport  # noqa: F401
except ImportError:
    from app.services.guardian.long_novel_guardian import LongNovelGuardian, GuardianReport  # noqa: F401


try:
    from app.services.guardian.foreshadow_service import ForeshadowService
except ImportError:
    from app.services.guardian.foreshadow_service import ForeshadowService  # noqa: F401

try:
    from app.services.guardian.continuity_service import ContinuityService
except ImportError:
    from app.services.guardian.continuity_service import ContinuityService  # noqa: F401

try:
    from app.services.guardian.ooc_detector import OOCDetector  # noqa: F401
except ImportError:
    from app.services.guardian.ooc_detector import OOCDetector  # noqa: F401

from app.services.guardian import causal_graph  # noqa: F401  # 独立部署因果图服务
