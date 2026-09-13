"""本地多模态后端 — 使用 transformers 加载本地视觉模型。

支持模型：Qwen2.5-VL、LLaVA、InternVL 等。
需要 GPU（或 MPS）和 transformers + torch 环境。
模型懒加载，首次调用时才下载/加载权重。
"""

import threading
from typing import Any

from app.services.multimodal.base import BaseMultimodalBackend, VisionResult
from app.services.json_helper import safe_json_loads

import logging

logger = logging.getLogger(__name__)


class LocalMultimodalBackend(BaseMultimodalBackend):
    """本地多模态后端（懒加载，线程安全）。"""

    backend_name = 'local'

    def __init__(self, model_name: str = 'Qwen/Qwen2.5-VL-7B-Instruct', device: str = 'cuda'):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._processor = None
        self._init_lock = threading.Lock()
        self._init_done = False
        self._load_error: str | None = None

    def _ensure_loaded(self):
        """懒加载模型（首次调用时执行，线程安全）。"""
        if self._init_done:
            return
        with self._init_lock:
            if self._init_done:
                return
            try:
                from transformers import AutoProcessor, AutoModelForVision2Seq
                import torch

                logger.info('[LocalMM] 正在加载模型: %s → %s', self.model_name, self.device)
                self._processor = AutoProcessor.from_pretrained(self.model_name, trust_remote_code=True)
                self._model = AutoModelForVision2Seq.from_pretrained(
                    self.model_name,
                    torch_dtype=torch.float16 if self.device == 'cuda' else torch.float32,
                    device_map=self.device if self.device == 'cuda' else None,
                    trust_remote_code=True,
                )
                if self.device != 'cuda':
                    self._model = self._model.to(self.device)
                self._init_done = True
                logger.info('[LocalMM] 模型加载完成: %s', self.model_name)
            except Exception as e:
                self._load_error = str(e)
                self._init_done = True  # 标记已尝试，避免重复加载
                logger.error('[LocalMM] 模型加载失败: %s', e)

    @property
    def is_available(self) -> bool:
        """检查模型是否可用。"""
        self._ensure_loaded()
        return self._model is not None

    async def analyze_image(
        self,
        image_url: str,
        prompt: str = '请详细描述这张图片中的角色外貌特征。',
    ) -> VisionResult:
        """使用本地模型分析图片。"""
        self._ensure_loaded()
        if self._model is None:
            return VisionResult(
                issues=[f'本地模型加载失败: {self._load_error}'],
                backend=f'local:{self.model_name}',
            )

        try:
            response_text = await self._run_inference(image_url, prompt)
            return VisionResult(
                description=response_text,
                raw_response=response_text,
                backend=f'local:{self.model_name}',
            )
        except Exception as e:
            logger.error('[LocalMM] 图片分析失败: %s', e)
            return VisionResult(
                issues=[f'本地推理失败: {e}'],
                backend=f'local:{self.model_name}',
            )

    async def compare_images(
        self,
        image_url_a: str,
        image_url_b: str,
        prompt: str = '对比这两张图片中同一角色的外貌，列出差异。请返回JSON: {"score": 0.0-1.0, "differences": [...]}',
    ) -> VisionResult:
        """使用本地模型对比两张图片。"""
        self._ensure_loaded()
        if self._model is None:
            return VisionResult(
                issues=[f'本地模型加载失败: {self._load_error}'],
                backend=f'local:{self.model_name}',
            )

        try:
            # 本地模型一次处理两张图
            combined_prompt = f'{prompt}\n图片1: {image_url_a}\n图片2: {image_url_b}'
            response_text = await self._run_inference(image_url_a, combined_prompt)

            parsed = safe_json_loads(response_text)
            score = 1.0
            differences = []
            if isinstance(parsed, dict):
                score = float(parsed.get('score', 1.0))
                differences = parsed.get('differences', [])

            return VisionResult(
                description=response_text,
                consistency_score=max(0.0, min(1.0, score)),
                issues=differences,
                raw_response=response_text,
                backend=f'local:{self.model_name}',
            )
        except Exception as e:
            logger.error('[LocalMM] 图片对比失败: %s', e)
            return VisionResult(
                issues=[f'本地对比失败: {e}'],
                backend=f'local:{self.model_name}',
            )

    async def _run_inference(self, image_url: str, prompt: str) -> str:
        """执行本地模型推理（在线程池中运行，避免阻塞事件循环）。"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_inference, image_url, prompt)

    def _sync_inference(self, image_url: str, prompt: str) -> str:
        """同步推理（在线程池中执行）。"""
        import torch

        messages = [
            {
                'role': 'user',
                'content': [
                    {'type': 'image', 'image': image_url},
                    {'type': 'text', 'text': prompt},
                ],
            }
        ]

        text_input = self._processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = self._processor(
            text=[text_input],
            images=[image_url],
            padding=True,
            return_tensors='pt',
        )
        inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        with torch.no_grad():
            output_ids = self._model.generate(**inputs, max_new_tokens=512)

        response = self._processor.batch_decode(
            output_ids[:, inputs['input_ids'].shape[1]:],
            skip_special_tokens=True,
        )
        return response[0].strip() if response else ''
