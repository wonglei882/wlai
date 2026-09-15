"""VisGuard 统一产出物模型（Artifact）。

设计意图：
- 预处理 / 生图 / 质检的结果统一包装为 Artifact 列表，由 type 驱动前端渲染，
  后端实现（本地/云端）遵循同一契约：
    type='control_image'    → format='png'，data 为 base64 控制图，前端显示预览
    type='provider_params'  → format='json'，data 为生图参数，前端自动带入生图请求
    type='inspection_report'→ format='json'，data 为质检结果
- 本地与云端实现返回相同结构，调用方不感知后端差异。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Artifact:
    """预处理/生图/质检的统一产出物。"""

    type: str  # 'control_image' | 'provider_params' | 'inspection_report' | ...
    format: str  # 'png' | 'json' | 'base64' | ...
    data: Any  # base64 字符串 / JSON 对象 / bytes
    metadata: dict = field(default_factory=dict)

    def to_b64(self) -> str | None:
        """format 为 base64 且 data 为 str 时返回原样（便于前端直接使用）。"""
        if self.format == 'base64' and isinstance(self.data, str):
            return self.data
        return None


@dataclass
class PreprocessResult:
    """预处理统一结果（本地与云端相同结构）。"""

    artifacts: list[Artifact]
    duration_ms: int
    preprocessor_type: str


@dataclass
class GenerationResult:
    """生图统一结果。"""

    artifacts: list[Artifact]
    duration_ms: int
    provider: str
    model: str = ''
    warnings: list[str] = field(default_factory=list)