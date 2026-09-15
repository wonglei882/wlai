"""内容安全检测服务（NSFW zero-shot 分类）。

设计（P0-3）:
- 实例经 main.py lifespan 注册到 app.state（进程内全局一份，不随请求重建）；
- 模型懒加载：首次 check 且启用时才下载/加载 openai/clip-vit-base-patch32；
- 线程池执行同步推理，不阻塞事件循环（同 VisGuard 其他重计算路径）；
- fail-open：模型不可用 / 检测异常时放行（审核不过度阻断生产）；
- 默认 visguard_content_safety_enabled=False 关闭（离线环境零成本放行）。

标签集: safe / nsfw / pornographic / violent / normal
判定: nsfw|pornographic|violent 三者概率最大值 > visguard_nsfw_threshold 即不过。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

logger = logging.getLogger(__name__)

_NSFW_LABELS = ('nsfw', 'pornographic', 'violent')


@dataclass
class SafetyResult:
    """内容安全检测结果。"""

    passed: bool
    score: float = 0.0  # NSFW 最终分数（0-1，passed=True 时也可能非零）
    reason: str = ''
    skipped: bool = False  # 未启用 / 无输入 / 模型不可用时的放行标记


class ContentSafetyService:
    """内容安全检测 — 懒加载模型 + 线程池推理 + fail-open。

    不采用类级单例（类级单例在测试中难以复位）；
    由 lifespan 创建一次并挂 app.state，测试直接构造实例。
    """

    def __init__(
        self,
        enabled: bool = False,
        device: str = 'cpu',
        model_name: str = 'openai/clip-vit-base-patch32',
        threshold: float = 0.5,
    ):
        self.enabled = enabled
        self.device = device
        self.model_name = model_name
        self.threshold = threshold

        # 懒加载状态（_load_model 在首次 _sync_check 时触发）
        self._model = None
        self._processor = None
        self._label_to_idx: dict[str, int] = {}
        self._load_error: str | None = None
        self._loaded = False

    # ------------------------------------------------------------------
    # 状态查询（纯属性，不触发模型加载/下载）
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        """模型是否已加载（False 不表示失败，可能只是尚未懒加载）。"""
        return self._model is not None

    @property
    def load_error(self) -> str | None:
        """最近一次加载失败的描述；从未失败为 None。"""
        return self._load_error

    # ------------------------------------------------------------------
    # 检测入口
    # ------------------------------------------------------------------

    async def check_bytes(self, image_bytes: bytes) -> SafetyResult:
        """bytes 入口：解码 + 线程池推理。"""
        if not self.enabled or not image_bytes:
            return SafetyResult(passed=True, skipped=True)
        try:
            image = Image.open(BytesIO(image_bytes)).convert('RGB')
        except Exception as e:  # noqa: BLE001 - 解码失败按放行处理（与 API 层校验职责分离）
            logger.warning('[VisGuard] 内容安全输入解码失败: %s', e)
            return SafetyResult(passed=True, skipped=True, reason='输入解码失败，已放行')
        return await self.check_image(image)

    async def check_image(self, image: Image.Image) -> SafetyResult:
        """PIL Image 入口（API 层已解码后使用）。"""
        if not self.enabled or image is None:
            return SafetyResult(passed=True, skipped=True)
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._sync_check, image)
        except Exception as e:  # noqa: BLE001 - 审核异常放行（fail-open）
            logger.error('[VisGuard] 内容安全检测异常: %s', e)
            return SafetyResult(passed=True, reason='')

    # ------------------------------------------------------------------
    # 同步推理（线程池内执行）
    # ------------------------------------------------------------------

    def _sync_check(self, image: Image.Image) -> SafetyResult:
        if self._model is None:
            self._load_model()
        if self._model is None:  # 加载失败 → 放行
            return SafetyResult(passed=True, reason='模型加载失败，已放行')

        import torch

        inputs = self._processor(images=image, return_tensors='pt').to(self.device)
        with torch.inference_mode():
            outputs = self._model(**inputs)
        probs = outputs.logits_per_image.softmax(dim=-1).cpu().detach().numpy()[0]

        nsfw_score = max(
            (
                probs[self._label_to_idx[label]]
                for label in _NSFW_LABELS
                if label in self._label_to_idx
            ),
            default=0.0,
        )
        if nsfw_score > self.threshold:
            return SafetyResult(
                passed=False,
                score=float(nsfw_score),
                reason=f'内容安全检测未通过 (NSFW 分数: {nsfw_score:.2f})',
            )
        return SafetyResult(passed=True, score=float(nsfw_score))

    def _load_model(self) -> None:
        """懒加载 CLIP zero-shot 分类模型（线程池内调用；失败记录 error 并放行）。"""
        if self._loaded:
            return
        self._loaded = True
        logger.info('[VisGuard] 加载内容安全检测模型: %s', self.model_name)
        try:
            from transformers import CLIPModel, CLIPProcessor

            model = CLIPModel.from_pretrained(self.model_name).to(self.device)
            model.eval()
            processor = CLIPProcessor.from_pretrained(self.model_name)

            labels = ['safe', 'nsfw', 'pornographic', 'violent', 'normal']
            self._label_to_idx = {label: i for i, label in enumerate(labels)}
            self._processor = processor
            self._model = model
            logger.info('[VisGuard] 内容安全检测模型已加载（阈值 %.2f）', self.threshold)
        except Exception as e:  # noqa: BLE001 - 模型下载/加载失败记录并放行
            self._load_error = str(e)
            logger.error('[VisGuard] 内容安全模型加载失败: %s', e)

    def unload(self) -> None:
        """释放模型（lifespan 关闭 / 测试复位时调用）。"""
        self._model = None
        self._processor = None
        self._label_to_idx = {}