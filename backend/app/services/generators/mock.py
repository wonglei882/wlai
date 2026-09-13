"""Mock 生成器 — 离线可用的占位实现。

用途：Demo / 测试 / 未接入真实平台时兜底。生成确定性占位素材（SVG 图片 / 文本文件），
保证漫剧流水线端到端可演示，不依赖任何外部 AI 服务。
"""

import uuid
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

from .base import GenerationResult, ImageGenerator, VideoGenerator, VoiceGenerator

GENERATED_DIR: Path = DATA_DIR / 'generated'
GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def _seed_from(parameters: dict[str, Any]) -> int:
    """从参数中解析确定性 seed（无 seed 时由 shot_id 派生）。"""
    s = parameters.get('seed')
    if isinstance(s, int) and s >= 0:
        return s
    raw = parameters.get('seed_text') or parameters.get('shot_id') or ''
    return abs(hash(raw)) % (10 ** 9)


class MockImageGenerator(ImageGenerator):
    """生成确定性 SVG 占位图，seed 控制配色，附提示词摘要。"""

    backend_name = 'mock-image'

    async def generate(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> GenerationResult:
        params = parameters or {}
        seed = _seed_from(params)
        fname = f'img_{uuid.uuid4().hex[:12]}.svg'
        fpath = GENERATED_DIR / fname
        fpath.write_text(self._render_svg(prompt, seed), encoding='utf-8')
        return GenerationResult(
            url=f'/generated/{fname}',
            file_path=str(fpath),
            media_type='image',
            prompt_used=prompt,
            parameters={'seed': seed, 'backend': self.backend_name},
            backend=self.backend_name,
        )

    @staticmethod
    def _render_svg(prompt: str, seed: int) -> str:
        import colorsys

        h = (seed % 360) / 360.0
        r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.85)
        bg = f'rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})'
        summary = (prompt or '')[:120].replace('&', '&amp;').replace('<', '&lt;')
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="576" viewBox="0 0 1024 576">\n'
            f'  <rect width="1024" height="576" fill="{bg}"/>\n'
            f'  <rect x="0" y="0" width="1024" height="576" fill="none" '
            f'stroke="#ffffff" stroke-opacity="0.15" stroke-width="2"/>\n'
            f'  <text x="512" y="260" text-anchor="middle" font-family="sans-serif" '
            f'font-size="34" fill="#ffffff" fill-opacity="0.9">WLai Mock 出图 #{seed}</text>\n'
            f'  <text x="512" y="310" text-anchor="middle" font-family="sans-serif" '
            f'font-size="16" fill="#ffffff" fill-opacity="0.6">{summary}</text>\n'
            f'</svg>'
        )


class MockVideoGenerator(VideoGenerator):
    """生成文本占位视频。"""

    backend_name = 'mock-video'

    async def generate(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> GenerationResult:
        params = parameters or {}
        seed = _seed_from(params)
        fname = f'video_{uuid.uuid4().hex[:12]}.txt'
        fpath = GENERATED_DIR / fname
        fpath.write_text(
            f'WLai Mock 视频占位\nseed={seed}\nprompt={(prompt or "")[:200]}',
            encoding='utf-8',
        )
        return GenerationResult(
            url=f'/generated/{fname}',
            file_path=str(fpath),
            media_type='video',
            prompt_used=prompt,
            parameters={'seed': seed, 'backend': self.backend_name},
            backend=self.backend_name,
        )


class MockVoiceGenerator(VoiceGenerator):
    """生成文本占位配音。"""

    backend_name = 'mock-voice'

    async def generate(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> GenerationResult:
        params = parameters or {}
        fname = f'voice_{uuid.uuid4().hex[:12]}.txt'
        fpath = GENERATED_DIR / fname
        fpath.write_text(f'WLai Mock 配音占位: {(prompt or "")[:200]}', encoding='utf-8')
        return GenerationResult(
            url=f'/generated/{fname}',
            file_path=str(fpath),
            media_type='voice',
            prompt_used=prompt,
            parameters=params,
            backend=self.backend_name,
        )
