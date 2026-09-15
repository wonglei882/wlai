"""VisGuard 配置快照 — 不可变冻结快照 + generation 热切换。

设计意图：
- 任务创建时调用 take_config_snapshot() 锁定当时配置（不可变），
  运行期间不受配置热重载影响：旧任务继续用旧快照，新任务取新快照。
- reload_config() 递增 generation 并重建快照；持有旧快照的任务自然完成后，
  其引用的旧后端实例被 GC 回收，无需显式引用计数。
- cloud_api_key_hash 只存哈希不存明文，to_dict() 永不泄漏密钥。
"""

import hashlib
import threading
from dataclasses import asdict, dataclass

from app.config import settings

_lock = threading.RLock()
_current: 'ConfigSnapshot | None' = None
_generation: int = 0


@dataclass(frozen=True)
class ConfigSnapshot:
    """任务创建时的配置快照（不可变）。"""

    generation: int
    embedding_backend: str
    preprocess_backend: str
    generate_backend: str
    inspect_backend: str
    clip_model: str
    clip_device: str
    cloud_provider: str
    cloud_api_key_hash: str
    preprocess_resolution: int
    default_threshold: float
    ui_preset: str

    def to_dict(self) -> dict:
        """导出可传输字段（剔除 generation 与密钥哈希）。"""
        data = asdict(self)
        data.pop('generation', None)
        data.pop('cloud_api_key_hash', None)
        return data


def _build_snapshot() -> 'ConfigSnapshot':
    api_key = (settings.openai_api_key or '').encode()
    return ConfigSnapshot(
        generation=_generation,
        embedding_backend=settings.visguard_embedding_backend,
        preprocess_backend=settings.visguard_preprocess_backend,
        generate_backend=settings.visguard_generate_backend,
        inspect_backend=settings.visguard_inspect_backend,
        clip_model=settings.visguard_clip_model,
        clip_device=settings.visguard_clip_device,
        cloud_provider=settings.visguard_cloud_provider,
        cloud_api_key_hash=hashlib.sha256(api_key).hexdigest()[:16],
        preprocess_resolution=settings.visguard_preprocess_resolution,
        default_threshold=settings.visguard_default_threshold,
        ui_preset=settings.visguard_ui_preset,
    )


def take_config_snapshot() -> 'ConfigSnapshot':
    """获取当前配置快照（惰性构建并缓存，线程安全）。"""
    global _current
    with _lock:
        if _current is None:
            _current = _build_snapshot()
        return _current


def reload_config() -> None:
    """热重载配置：递增 generation 并重建快照。"""
    global _current, _generation
    with _lock:
        _generation += 1
        _current = _build_snapshot()


def get_snapshot_generation() -> int:
    """当前配置世代号（测试与观测用）。"""
    with _lock:
        return _generation


def reset_for_tests() -> None:
    """重置内部状态（测试隔离用）。"""
    global _current, _generation
    with _lock:
        _current = None
        _generation = 0