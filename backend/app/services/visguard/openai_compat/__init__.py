"""OpenAI 兼容接口（VisGuard 内嵌版）。

兼容性声明（详见 README.md）:

    ✅ 已实现: POST /api/v1/visguard/openai/images/generations
        - 请求/响应 schema 对齐 OpenAI POST /v1/images/generations
        - 差异: 必须附加 VisGuard 扩展字段 project_id（项目归属校验）；
                model 参数被忽略；仅支持 response_format="b64_json"、n=1；
                ip_adapter/control_type 扩展字段仅在 Phase C 生图后端落地后生效
    ❌ 501:   POST /chat/completions、POST /embeddings、GET /models

认证: 复用 WLai JWT（Authorization: Bearer <wlai_token>），与平台一致（非 VG_API_KEYS）。
"""

from app.services.visguard.openai_compat.images import (
    ImageData,
    ImagesGenerationRequest,
    ImagesGenerationResponse,
    openai_error_detail,
    to_visguard_params,
)

__all__ = [
    'ImageData',
    'ImagesGenerationRequest',
    'ImagesGenerationResponse',
    'openai_error_detail',
    'to_visguard_params',
]