"""VisGuard 服务门面 — 角色视觉一致性（能力矩阵架构）。

架构（v2：能力矩阵替代全局 mode；P0-2 工厂注册表接入）::

    VisGuardService（门面，单例）
      ├── FactoryRegistry            # 能力工厂（generate 等）原子构建 + 热重载
      ├── ClipEncoder                # 共享实例，embedding 恒定本地跑
      └── CharacterBank[]            # 按 project_id 缓存，目录隔离

配置（app.config.Settings）:
    visguard_embedding_backend='local'   — 唯一选项（CLIP 本地）
    visguard_preprocess_backend/generate_backend/inspect_backend
        — 各能力独立后端；全部 'none' 时 get_visguard_service() 返回 None（API 层 503）
    （预处理/生图/质检策略经 FactoryRegistry 扩展与热重载，门面保持稳定）

热重载（P0-2）:
    service.reload_capabilities()  — 重读配置并原子重建受影响工厂（失败回滚保留旧实例）；
    status()['capabilities']['generate']['ready'] / ['generation'] 反映当前实例与代次。

注意: 单例需在测试中重置 —— reset_visguard_service()（同 multimodal 约定）。
"""

import logging
import threading

from app.config import settings
from app.services.visguard.character_bank import CharacterBank
from app.services.visguard.clip_encoder import ClipEncoder
from app.services.visguard.core.cache import CacheManager
from app.services.visguard.core.capabilities import get_capabilities, is_visguard_enabled
from app.services.visguard.core.factory_registry import FactoryRegistry
from app.services.visguard.generation.factory import create_generator

logger = logging.getLogger(__name__)


class VisGuardService:
    """VisGuard 门面：共享 CLIP 编码器，按项目缓存角色资产库。"""

    def __init__(
        self,
        clip_model: str | None = None,
        clip_device: str | None = None,
        index_root: str | None = None,
        default_threshold: float | None = None,
    ):
        self.clip_model = clip_model or settings.visguard_clip_model
        self.clip_device = clip_device or settings.visguard_clip_device
        self.index_root = index_root or settings.visguard_index_root
        self.default_threshold = (
            default_threshold
            if default_threshold is not None
            else settings.visguard_default_threshold
        )
        self.embedding_backend = settings.visguard_embedding_backend

        # 服务级三级缓存（预处理/生图/相似度结果缓存，配额受限防爆盘）
        self.cache = CacheManager(
            cache_dir=settings.visguard_cache_dir,
            max_size_mb=settings.visguard_cache_max_mb,
        )

        # 能力工厂注册表（P0-2）：'generate' -> create_generator（后续能力按需注册）
        self.registry = FactoryRegistry()
        self.registry.register('generate', lambda: create_generator())

        self.clip = ClipEncoder(self.clip_model, self.clip_device)
        self._banks: dict[str, CharacterBank] = {}
        self._bank_lock = threading.Lock()

    def reload_capabilities(self) -> dict[str, bool]:
        """热重载能力工厂（重读配置后原子重建；失败回滚保留旧实例）。

        Returns:
            {工厂名: 重建是否成功}；未注册工厂不在结果中。
        """
        return self.registry.reload_all()

    def get_bank(self, project_id: str) -> CharacterBank:
        """获取（或创建）某项目的角色资产库。"""
        with self._bank_lock:
            bank = self._banks.get(project_id)
            if bank is None:
                bank = CharacterBank(
                    project_id=project_id,
                    base_dir=self.index_root,
                    clip=self.clip,
                    default_threshold=self.default_threshold,
                )
                self._banks[project_id] = bank
                logger.info('[VisGuard] 初始化项目角色库: %s', project_id)
            return bank

    def drop_bank(self, project_id: str) -> None:
        """释放某项目的角色库缓存（项目删除时调用，避免内存/句柄泄漏）。"""
        with self._bank_lock:
            self._banks.pop(project_id, None)

    def status(self) -> dict:
        """服务状态（供 /api/v1/visguard/status 与能力发现面板）。"""
        caps = get_capabilities()
        generator = self.registry.get('generate')  # 可能为 None（generate=none 或构建失败）
        generate_generation = self.registry.generation('generate')
        with self._bank_lock:
            bank_info = [
                {
                    'project_id': pid,
                    'characters': len(bank.list_characters()),
                    'embeddings': bank.index.size,
                }
                for pid, bank in self._banks.items()
            ]
        return {
            'capabilities': {
                'embedding': {
                    'available': caps.embedding,
                    'backend': getattr(settings, 'visguard_embedding_backend', 'local'),
                },
                'preprocess': {
                    'available': bool(caps.preprocess),
                    'types': caps.preprocess,
                    'backend': getattr(settings, 'visguard_preprocess_backend', 'none'),
                },
                'generate': {
                    'available': caps.generate,
                    'backend': getattr(settings, 'visguard_generate_backend', 'none'),
                    'provider': (
                        settings.visguard_cloud_provider if caps.generate else None
                    ),
                    'ready': generator is not None,
                    'generation': generate_generation,
                },
                'inspect': {
                    'available': caps.inspect,
                    'backend': caps.inspect_backend,
                },
            },
            'clip': {
                'model': self.clip_model,
                'device': self.clip_device,
                'available': self.clip.is_loaded,  # 纯状态查询，不触发模型下载
                'load_error': self.clip.load_error,
                'load_error_occurred': self.clip.load_error is not None,
            },
            'default_threshold': self.default_threshold,
            'index_root': self.index_root,
            'projects': bank_info,
            'total_characters': sum(b['characters'] for b in bank_info),
            'cache': self.cache.stats(),
        }


# ----------------------------------------------------------------------
# 单例工厂（与 app.services.multimodal 约定一致）
# ----------------------------------------------------------------------

_instance: VisGuardService | None = None
_initialized = False


def get_visguard_service() -> VisGuardService | None:
    """获取 VisGuard 服务单例。

    Returns:
        VisGuardService: 服务实例；能力矩阵全部关闭时返回 None（调用方应返回 503）。
    """
    global _instance, _initialized
    if _initialized:
        return _instance

    if not is_visguard_enabled():
        _instance = None
        logger.info('[VisGuard] 已禁用（能力矩阵全部关闭）')
    else:
        _instance = VisGuardService()
        logger.info(
            '[VisGuard] 服务就绪: emb=%s pre=%s gen=%s insp=%s, clip=%s@%s',
            _instance.embedding_backend,
            settings.visguard_preprocess_backend,
            settings.visguard_generate_backend,
            settings.visguard_inspect_backend,
            _instance.clip_model, _instance.clip_device,
        )
    _initialized = True
    return _instance


def reset_visguard_service() -> None:
    """重置单例（测试用；释放 CLIP 显存）。"""
    global _instance, _initialized
    if _instance is not None:
        _instance.clip.unload()
    _instance = None
    _initialized = False


__all__ = [
    'VisGuardService',
    'CharacterBank',
    'ClipEncoder',
    'get_visguard_service',
    'reset_visguard_service',
]