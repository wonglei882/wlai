"""内容安全服务测试（P0-3）。

要点：
- 默认禁用（enabled=False）→ 全放行（skipped），离线零成本；
- 启用但不注入模型 → fail-open（加载失败/异常放行）；
- mock 检测逻辑验证 passed/score/reason；
- 不触发真实 HF 模型下载（懒加载路径用 mock 覆盖）。
"""

from io import BytesIO
from unittest.mock import patch

import pytest
from app.services.visguard.core.content_safety import ContentSafetyService, SafetyResult
from PIL import Image


def _make_png() -> bytes:
    buf = BytesIO()
    Image.new('RGB', (64, 64), color=(120, 120, 120)).save(buf, format='PNG')
    return buf.getvalue()


def _make_pil() -> Image.Image:
    return Image.new('RGB', (64, 64), color=(200, 120, 40))


# =============================================================================
# 未启用 → 全放行
# =============================================================================


class TestDisabled:
    @pytest.mark.asyncio
    async def test_check_bytes_passes(self):
        svc = ContentSafetyService(enabled=False)
        result = await svc.check_bytes(_make_png())
        assert result.passed is True
        assert result.skipped is True

    @pytest.mark.asyncio
    async def test_check_image_passes(self):
        svc = ContentSafetyService(enabled=False)
        result = await svc.check_image(_make_pil())
        assert result.passed is True
        assert result.skipped is True

    @pytest.mark.asyncio
    async def test_empty_bytes_passes(self):
        svc = ContentSafetyService(enabled=True)
        result = await svc.check_bytes(b'')
        assert result.passed is True
        assert result.skipped is True


# =============================================================================
# 启用 + fail-open（不触发真实模型下载）
# =============================================================================


class TestFailOpen:
    @pytest.mark.asyncio
    async def test_load_failure_passes(self):
        """模型加载失败 → 放行且记录 load_error。"""
        svc = ContentSafetyService(enabled=True)
        with patch.object(
            svc, '_load_model',
            side_effect=Exception('mock 下载失败'),
        ):
            result = await svc.check_image(_make_pil())
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_inference_exception_passes(self):
        """线程池推理异常 → 放行（fail-open）。"""
        svc = ContentSafetyService(enabled=True)
        with patch.object(svc, '_sync_check', side_effect=RuntimeError('boom')):
            result = await svc.check_image(_make_pil())
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_invalid_bytes_passes(self):
        """解码失败 → 放行。"""
        svc = ContentSafetyService(enabled=True)
        result = await svc.check_bytes(b'not-an-image')
        assert result.passed is True
        assert result.skipped is True


# =============================================================================
# mock 检测逻辑
# =============================================================================


class TestMockedInference:
    @pytest.mark.asyncio
    async def test_nsfw_detected(self):
        svc = ContentSafetyService(enabled=True, threshold=0.5)
        with patch.object(
            svc, '_sync_check',
            return_value=SafetyResult(passed=False, score=0.93, reason='NSFW 0.93'),
        ):
            result = await svc.check_image(_make_pil())
        assert result.passed is False
        assert 'NSFW' in result.reason

    @pytest.mark.asyncio
    async def test_safe_passes(self):
        svc = ContentSafetyService(enabled=True, threshold=0.5)
        with patch.object(
            svc, '_sync_check',
            return_value=SafetyResult(passed=True, score=0.02),
        ):
            result = await svc.check_image(_make_pil())
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_check_bytes_forwards_to_check_image(self):
        """check_bytes 解码后复用 check_image 逻辑。"""
        svc = ContentSafetyService(enabled=True)
        with patch.object(
            svc, '_sync_check',
            return_value=SafetyResult(passed=True, score=0.0),
        ) as mock_fn:
            result = await svc.check_bytes(_make_png())
        assert result.passed is True
        mock_fn.assert_called_once()  # 已解码 → 线程池推理执行

    @pytest.mark.asyncio
    async def test_sync_check_loads_model_lazily(self):
        """_sync_check 内部首次调 _load_model。"""
        svc = ContentSafetyService(enabled=True)
        with patch.object(svc, '_load_model') as mock_load:
            # _model 为 None（未加载）；直接调 _sync_check 会走 _load_model
            svc._sync_check(_make_pil())
        mock_load.assert_called_once()

    def test_unload_resets(self):
        svc = ContentSafetyService(enabled=True)
        svc._model = object()
        svc._processor = object()
        svc.unload()
        assert svc._model is None
        assert svc._processor is None

    def test_state_query_does_not_load(self):
        """is_loaded / load_error 是纯属性，不触发模型加载。"""
        svc = ContentSafetyService(enabled=True)
        assert svc.is_loaded is False
        assert svc.load_error is None