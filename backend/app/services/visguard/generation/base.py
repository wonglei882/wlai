"""生成器抽象 — 云端出图适配器的统一接口（Phase C 落地实现）。"""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

from app.services.visguard.core.artifact import GenerationResult


@dataclass
class GenerationParams:
    """生图统一参数（供应商无关，适配器内部映射）。"""

    prompt: str
    negative_prompt: str = ''
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg: float = 7.0
    seed: int | None = None
    character_ids: list[str] = field(default_factory=list)  # 视觉参考角色
    control_type: str | None = None
    control_weight: float = 0.8
    provider: str = ''
    model: str = ''

    def model_dump(self) -> dict:
        """转 dict（供任务参数快照/幂等键使用）。"""
        return asdict(self)


class BaseGenerator(ABC):
    """生成器抽象基类。"""

    backend_name: str = 'base'

    @abstractmethod
    async def generate(self, params: GenerationParams) -> GenerationResult:
        """执行生图并返回统一结果。"""
        raise NotImplementedError