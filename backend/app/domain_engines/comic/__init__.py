"""漫剧领域引擎 — 5 个扫描维度。"""

from app.domain_engines.comic.dialogue_scanner import DialogueBubbleScanner  # noqa: F401
from app.domain_engines.comic.panel_scanner import PanelTransitionScanner  # noqa: F401
from app.domain_engines.comic.quality_scorer import ComicQualityScorer  # noqa: F401
from app.domain_engines.comic.scene_scanner import SceneContinuityScanner  # noqa: F401
from app.domain_engines.comic.visual_scanner import VisualConsistencyScanner  # noqa: F401
