"""VisGuard OpenAI 兼容层测试（P0-5）。

覆盖:
- schema 校验：n>1 / response_format≠b64_json / 非法 size → 拒绝
- 参数映射：to_visguard_params 正确产出 GenerationParams
- 错误格式：openai_error_detail → handler 透传为 {"error": {...}}（顶层键）
端点级测试见 tests/api/test_visguard_openai_api.py（api_env 集成基座）。
"""

import pytest
from app.services.visguard.openai_compat.images import (
    ImageData,
    ImagesGenerationRequest,
    ImagesGenerationResponse,
    openai_error_detail,
    to_visguard_params,
    validate_body,
)
from pydantic import ValidationError

# =============================================================================
# schema 校验
# =============================================================================


class TestRequestSchema:
    def _ok(self, **overrides):
        base = {'project_id': 'p1', 'prompt': '测试提示'}
        base.update(overrides)
        return base

    def test_minimal_valid(self):
        req = ImagesGenerationRequest(**self._ok())
        assert req.prompt == '测试提示'
        assert req.n == 1
        assert req.response_format == 'b64_json'

    def test_project_id_required(self):
        with pytest.raises(ValidationError):
            ImagesGenerationRequest(prompt='无项目归属')

    def test_prompt_required(self):
        with pytest.raises(ValidationError):
            ImagesGenerationRequest(project_id='p1')

    def test_n_gt_1_rejected(self):
        with pytest.raises(ValidationError):
            ImagesGenerationRequest(**self._ok(n=2))

    def test_control_extensions_accepted(self):
        req = ImagesGenerationRequest(**self._ok(
            character_id='c1',
            control_type='canny',
            control_weight=0.6,
            ip_adapter_type='faceid',
            ip_adapter_weight=0.4,
        ))
        assert req.character_id == 'c1'
        assert req.control_weight == 0.6


class TestValidateBody:
    def test_b64_json_ok(self):
        assert validate_body(ImagesGenerationRequest(project_id='p1', prompt='x')) is None

    def test_url_format_rejected(self):
        req = ImagesGenerationRequest(
            project_id='p1', prompt='x', response_format='url',
        )
        err = validate_body(req)
        assert err is not None
        assert 'b64_json' in err

    def test_unsupported_size_rejected(self):
        req = ImagesGenerationRequest(project_id='p1', prompt='x', size='800x600')
        err = validate_body(req)
        assert err is not None
        assert 'size' in err

    def test_supported_size_ok(self):
        req = ImagesGenerationRequest(project_id='p1', prompt='x', size='1024x1024')
        assert validate_body(req) is None


# =============================================================================
# 参数映射
# =============================================================================


class TestToVisguardParams:
    def test_basic_mapping(self):
        body = ImagesGenerationRequest(project_id='p1', prompt='英雄登场', size='1024x1024')
        p = to_visguard_params(body)
        assert p.prompt == '英雄登场'
        assert p.width == 1024 and p.height == 1024
        assert p.character_ids == []

    def test_character_id_maps_to_list(self):
        body = ImagesGenerationRequest(project_id='p1', prompt='x', character_id='ch-1')
        p = to_visguard_params(body)
        assert p.character_ids == ['ch-1']

    def test_control_requires_image(self):
        # 只有 control_type 没有 control_image_b64 → 忽略 control
        body = ImagesGenerationRequest(project_id='p1', prompt='x', control_type='canny')
        p = to_visguard_params(body)
        assert p.control_type is None

        body2 = ImagesGenerationRequest(
            project_id='p1', prompt='x', control_type='canny', control_image_b64='aGk=',
        )
        p2 = to_visguard_params(body2)
        assert p2.control_type == 'canny'
        assert p2.control_weight == 0.8

    def test_invalid_size_raises(self):
        body = ImagesGenerationRequest(project_id='p1', prompt='x', size='garbage')
        with pytest.raises(ValueError):
            to_visguard_params(body)

    def test_default_size_falls_back(self):
        body = ImagesGenerationRequest(project_id='p1', prompt='x', size=None)
        p = to_visguard_params(body)
        assert p.width == 1024 and p.height == 1024


# =============================================================================
# 错误格式 + 响应模型
# =============================================================================


class TestErrorFormat:
    def test_error_detail_shape(self):
        detail = openai_error_detail('预算不足', code='insufficient_quota')
        # detail 是 error 对象本体；handler content={'error': detail} 透传为顶层
        assert detail == {
            'message': '预算不足',
            'type': 'invalid_request_error',
            'code': 'insufficient_quota',
        }

    def test_response_model(self):
        resp = ImagesGenerationResponse(data=[ImageData(b64_json='abc', revised_prompt='x')])
        assert resp.created > 0
        assert resp.data[0].b64_json == 'abc'