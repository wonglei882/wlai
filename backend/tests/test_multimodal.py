"""测试多模态服务层（工厂 + 各后端）。"""

import pytest
from unittest.mock import patch, MagicMock

from app.services.multimodal import (
    get_multimodal_service,
    reset_multimodal_service,
    VisionResult,
)
from app.services.multimodal.none_backend import NoneMultimodalBackend
from app.services.multimodal.cloud_backend import CloudMultimodalBackend
from app.services.multimodal.local_backend import LocalMultimodalBackend
from app.services.multimodal.base import BaseMultimodalBackend


class TestMultimodalFactory:
    """工厂函数测试。"""

    def setup_method(self):
        reset_multimodal_service()

    def teardown_method(self):
        reset_multimodal_service()

    def test_default_is_none_backend(self):
        """默认配置应返回 NoneMultimodalBackend。"""
        with patch('app.config.settings') as mock_settings:
            mock_settings.multimodal_backend = 'none'
            svc = get_multimodal_service()
            assert isinstance(svc, NoneMultimodalBackend)
            assert svc.backend_name == 'none'
            assert svc.is_available is False

    def test_cloud_backend_creation(self):
        """配置 cloud 应返回 CloudMultimodalBackend。"""
        with patch('app.config.settings') as mock_settings:
            mock_settings.multimodal_backend = 'cloud'
            mock_settings.multimodal_cloud_provider = 'openai'
            mock_settings.multimodal_cloud_model = 'gpt-4o'
            svc = get_multimodal_service()
            assert isinstance(svc, CloudMultimodalBackend)
            assert svc.backend_name == 'cloud'
            assert svc.provider == 'openai'
            assert svc.model == 'gpt-4o'

    def test_local_backend_creation(self):
        """配置 local 应返回 LocalMultimodalBackend。"""
        with patch('app.config.settings') as mock_settings:
            mock_settings.multimodal_backend = 'local'
            mock_settings.multimodal_local_model = 'Qwen/Qwen2.5-VL-7B-Instruct'
            mock_settings.multimodal_local_device = 'cuda'
            svc = get_multimodal_service()
            assert isinstance(svc, LocalMultimodalBackend)
            assert svc.backend_name == 'local'
            assert svc.model_name == 'Qwen/Qwen2.5-VL-7B-Instruct'

    def test_unknown_backend_falls_back_to_none(self):
        """未知后端类型应回退到 none。"""
        with patch('app.config.settings') as mock_settings:
            mock_settings.multimodal_backend = 'invalid_backend'
            svc = get_multimodal_service()
            assert isinstance(svc, NoneMultimodalBackend)

    def test_singleton_pattern(self):
        """工厂应返回单例。"""
        with patch('app.config.settings') as mock_settings:
            mock_settings.multimodal_backend = 'none'
            svc1 = get_multimodal_service()
            svc2 = get_multimodal_service()
            assert svc1 is svc2


class TestNoneBackend:
    """None 后端测试。"""

    @pytest.mark.asyncio
    async def test_analyze_returns_empty_result(self):
        """analyze_image 应返回空结果。"""
        backend = NoneMultimodalBackend()
        result = await backend.analyze_image('http://example.com/img.png')
        assert result.backend == 'none'
        assert result.description == ''
        assert len(result.issues) > 0
        assert '未启用' in result.issues[0]

    @pytest.mark.asyncio
    async def test_compare_returns_perfect_score(self):
        """compare_images 应返回 consistency_score=1.0。"""
        backend = NoneMultimodalBackend()
        result = await backend.compare_images('http://a.png', 'http://b.png')
        assert result.consistency_score == 1.0
        assert result.backend == 'none'

    def test_is_available_false(self):
        """is_available 应为 False。"""
        backend = NoneMultimodalBackend()
        assert backend.is_available is False


class TestCloudBackend:
    """Cloud 后端测试（不实际调用 API）。"""

    def test_backend_name(self):
        backend = CloudMultimodalBackend(provider='openai', model='gpt-4o')
        assert backend.backend_name == 'cloud'
        assert backend.provider == 'openai'
        assert backend.model == 'gpt-4o'

    @pytest.mark.asyncio
    async def test_analyze_handles_error_gracefully(self):
        """API 调用失败时应返回带 issues 的 VisionResult。"""
        backend = CloudMultimodalBackend(provider='openai', model='gpt-4o')
        with patch.object(backend, '_call_openai_vision', side_effect=Exception('API key invalid')):
            result = await backend.analyze_image('http://example.com/img.png')
            assert result.backend == 'cloud:openai/gpt-4o'
            assert len(result.issues) > 0
            assert 'API key invalid' in result.issues[0]

    @pytest.mark.asyncio
    async def test_compare_handles_error_gracefully(self):
        """API 调用失败时应返回带 issues 的 VisionResult。"""
        backend = CloudMultimodalBackend(provider='openai', model='gpt-4o')
        with patch.object(backend, '_call_openai_vision', side_effect=Exception('timeout')):
            result = await backend.compare_images('http://a.png', 'http://b.png')
            assert result.backend == 'cloud:openai/gpt-4o'
            assert len(result.issues) > 0


class TestLocalBackend:
    """Local 后端测试（不实际加载模型）。"""

    def test_backend_name(self):
        backend = LocalMultimodalBackend(model_name='test-model', device='cpu')
        assert backend.backend_name == 'local'
        assert backend.model_name == 'test-model'
        assert backend.device == 'cpu'

    def test_is_available_false_before_load(self):
        """模型未加载时 is_available 应为 False（transformers 不可用时）。"""
        backend = LocalMultimodalBackend(model_name='nonexistent-model', device='cpu')
        assert backend.is_available is False

    @pytest.mark.asyncio
    async def test_analyze_returns_error_when_model_not_loaded(self):
        """模型加载失败时 analyze 应返回错误信息。"""
        backend = LocalMultimodalBackend(model_name='nonexistent-model', device='cpu')
        result = await backend.analyze_image('http://example.com/img.png')
        assert result.backend == 'local:nonexistent-model'
        assert len(result.issues) > 0


class TestVisionResult:
    """VisionResult 数据类测试。"""

    def test_default_values(self):
        result = VisionResult()
        assert result.description == ''
        assert result.objects == []
        assert result.consistency_score == 1.0
        assert result.issues == []
        assert result.backend == 'none'

    def test_custom_values(self):
        result = VisionResult(
            description='黑发少女',
            consistency_score=0.85,
            issues=['发色变化'],
            backend='cloud:openai/gpt-4o',
        )
        assert result.description == '黑发少女'
        assert result.consistency_score == 0.85
        assert result.issues == ['发色变化']
        assert result.backend == 'cloud:openai/gpt-4o'
