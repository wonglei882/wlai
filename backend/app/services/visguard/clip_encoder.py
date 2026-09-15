"""VisGuard CLIP 编码器 — 角色视觉特征向量提取。

使用 transformers 加载 CLIP 模型（默认 openai/clip-vit-large-patch14），
把参考图编码为 L2 归一化 embedding，供 FAISS 索引做余弦近邻检索。

设计决策（与既有 LocalMultimodalBackend 一致 + VisGuard 特殊考量）：
- **本地推理**：embedding 能力恒定本地跑——轻量（<2GB 显存）、角色数据私有不上云、
  避免云端 CLIP API 延迟与费用（能力矩阵中 embedding_backend 仅 'local'）。
- **懒加载**：首次编码时才加载模型（初始化开销大），线程安全（双检锁）。
- **fail-graceful**：模型加载失败 → is_loaded=False，encode 抛
  ClipUnavailableError（由上层转为可读的 503 响应），不 crash 进程。
- **状态查询不触发加载**：is_loaded/load_error 纯查询属性，
  供 status/capabilities 等轻量端点使用；只有真正编码才触发模型下载。

参考: backend/app/services/multimodal/local_backend.py（同款懒加载模式）。
"""

import logging
import threading

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

from app.services.visguard.core.exceptions import ClipUnavailableError  # noqa: E402 - 统一异常层级


class ClipEncoder:
    """CLIP 图像编码器（线程安全，首次调用懒加载）。"""

    def __init__(self, model_name: str, device: str = 'cuda'):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._processor = None
        self._lock = threading.Lock()  # 懒加载锁
        self._infer_lock = threading.Lock()  # 推理串行化锁（CUDA 流非线程安全）
        self._init_done = False
        self._load_error: str | None = None

    # ------------------------------------------------------------------
    # 可用性
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """模型是否可用（触发懒加载；失败后返回 False 且不再重试）。"""
        self._ensure_loaded()
        return self._model is not None

    @property
    def is_loaded(self) -> bool:
        """是否已成功加载（纯状态查询，不触发模型下载 —— 供 status/能力发现使用）。"""
        return self._init_done and self._model is not None

    @property
    def load_error(self) -> str | None:
        """最近一次加载失败原因（未失败为 None）。"""
        return self._load_error

    @property
    def embedding_dimension(self) -> int:
        """embedding 维度（模型加载后有效；未加载时按配置模型推断 fail-safe 768）。"""
        if self._model is not None:
            return self._model.config.projection_dim
        if 'base' in self.model_name:
            return 512
        return 768

    # ------------------------------------------------------------------
    # 懒加载
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """双检锁懒加载 transformers CLIPModel + CLIPProcessor。"""
        if self._init_done:
            return
        with self._lock:
            if self._init_done:
                return
            try:
                import torch  # noqa: F401 - 触发 torch 导入，用于后续 dtype 判断
                from transformers import CLIPModel, CLIPProcessor

                logger.info(
                    '[VisGuard] 加载 CLIP 模型: %s → %s', self.model_name, self.device
                )
                self._processor = CLIPProcessor.from_pretrained(self.model_name)
                self._model = CLIPModel.from_pretrained(self.model_name)
                if self.device != 'cpu':
                    self._model = self._model.to(self.device)
                self._model.eval()
                self._init_done = True
                logger.info('[VisGuard] CLIP 加载完成: %s', self.model_name)
            except Exception as e:  # noqa: BLE001 - 网络/显存/硬件兼容错误种类多
                self._load_error = str(e)
                self._init_done = True  # 标记已尝试，避免反复加载
                logger.error('[VisGuard] CLIP 加载失败: %s', e)

    # ------------------------------------------------------------------
    # 编码
    # ------------------------------------------------------------------

    def encode_image(self, image: Image.Image) -> np.ndarray:
        """单张图片 → L2 归一化 embedding（float32, (D,)）。

        Args:
            image: RGB PIL Image。

        Returns:
            np.ndarray: 归一化特征向量（FAISS IndexFlatIP 可直接点积检索）。

        Raises:
            ClipUnavailableError: 模型不可用或编码失败。
        """
        vectors = self.encode_images([image])
        return vectors[0]

    def encode_images(self, images: list[Image.Image]) -> np.ndarray:
        """批量编码（单次前向）→ (N, D) L2 归一化向量矩阵。

        Raises:
            ClipUnavailableError: 模型不可用或编码失败。
        """
        self._ensure_loaded()
        if self._model is None:
            raise ClipUnavailableError(
                f'CLIP 模型不可用: {self._load_error or "未加载"}'
            )

        # 推理锁：多 worker 并发编码时串行化前向（部分 CUDA 驱动/Transformers
        # 版本下同流并发 forward 不安全），代价是吞吐换稳定性——批量 encode_images
        # 仍一次前向，实际影响可忽略。
        with self._infer_lock:
            try:
                import torch

                inputs = self._processor(
                    images=[img.convert('RGB') for img in images],
                    return_tensors='pt',
                )
                inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

                with torch.no_grad():
                    features = self._model.get_image_features(**inputs)
                    features = torch.nn.functional.normalize(features, p=2, dim=-1)

                return features.detach().cpu().numpy().astype(np.float32)
            except ClipUnavailableError:
                raise
            except Exception as e:  # noqa: BLE001 - 上游框架异常统一转业务异常
                logger.error('[VisGuard] CLIP 编码失败: %s', e)
                raise ClipUnavailableError(f'CLIP 编码失败: {e}') from e

    def unload(self) -> None:
        """卸载模型释放显存（模式切换 / 资源回收时调用）。"""
        with self._lock:
            if self._model is not None:
                try:
                    import torch

                    del self._model
                    del self._processor
                    if self.device != 'cpu':
                        torch.cuda.empty_cache()
                except Exception as e:  # noqa: BLE001
                    logger.warning('[VisGuard] CLIP 卸载失败: %s', e)
                self._model = None
                self._processor = None
                self._init_done = False
                self._load_error = None
                logger.info('[VisGuard] CLIP 已卸载')