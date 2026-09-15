"""OpenAI 兼容 Images API — schema 与参数映射（纯逻辑，可单测）。

请求格式对齐 OpenAI POST /v1/images/generations；响应格式对齐 ImagesResponse。
差异（见 README.md）:
- 必须附加 VisGuard 扩展字段 project_id（归属校验所需）
- model 参数接受但忽略（由 VisGuard 配置决定）
- 仅支持 n=1、response_format="b64_json"
- 扩展字段（character_id/control_type/ip_adapter_*）Phase C 生图后端落地后生效

错误形状: OpenAI error object（{message, type, code}），由 HTTPException detail 承载
（main.py 全局 handler content={'error': detail} 恰好透传该形状）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.services.visguard.generation.base import GenerationParams

# OpenAI 支持的尺寸（与 VisGuard 供应商矩阵 max_resolution 对齐）
_SUPPORTED_SIZES = {
    '256x256',
    '512x512',
    '1024x1024',
    '1024x1792',
    '1792x1024',
    '2048x2048',
}


# =============================================================================
# 请求 / 响应模型（对齐 OpenAI schema）
# =============================================================================


class ImagesGenerationRequest(BaseModel):
    """OpenAI POST /v1/images/generations 请求体（+ VisGuard 扩展字段）。"""

    prompt: str = Field(..., min_length=1, max_length=4000)
    model: str | None = None  # 接受但忽略（VisGuard 配置决定模型）
    n: int = Field(default=1, ge=1, le=1)  # 仅支持 n=1
    quality: str | None = 'standard'  # 接受但不映射（Phase C 视供应商支持情况透传）
    response_format: str | None = 'b64_json'  # 仅支持 b64_json
    size: str | None = '1024x1024'
    style: str | None = None
    user: str | None = None

    # ── VisGuard 扩展参数（OpenAI SDK 无需感知，兼容客户端自行附加） ──
    project_id: str = Field(..., min_length=1)  # 必填：项目归属校验
    character_id: str | None = None
    control_type: str | None = None
    control_image_b64: str | None = None
    control_weight: float = Field(default=0.8, ge=0.0, le=1.0)
    ip_adapter_type: str | None = None
    ip_adapter_image_b64: str | None = None
    ip_adapter_weight: float = Field(default=0.35, ge=0.0, le=1.0)


class ImageData(BaseModel):
    """对齐 OpenAI images response data item。"""

    b64_json: str
    revised_prompt: str | None = None


class ImagesGenerationResponse(BaseModel):
    """对齐 OpenAI ImagesResponse（created + data）。"""

    created: int = Field(default_factory=lambda: int(datetime.now().timestamp()))
    data: list[ImageData]


def openai_error_detail(
    message: str,
    *,
    error_type: str = 'invalid_request_error',
    code: str = 'invalid_request',
) -> dict:
    """构造 OpenAI 风格 error 对象（作为 HTTPException detail 使用）。

    注意：main.py 全局 HTTPException handler 输出 content={'error': detail}，
    因此这里返回的应是 OpenAI error 对象本体（不含外层 'error' 键），
    最终 wire 形状才恰为 OpenAI 的 {"error": {"message","type","code"}}。
    """
    return {
        'message': message,
        'type': error_type,
        'code': code,
    }


# =============================================================================
# 参数映射（OpenAI 请求 → VisGuard 内部）
# =============================================================================


def to_visguard_params(body: ImagesGenerationRequest) -> GenerationParams:
    """OpenAI 请求 → GenerationParams（仅映射已实现的字段）。

    限制:
    - 仅支持 b64_json（其他 response_format 应在上游校验后 422）
    - size 形如 "1024x1024"；不支持的尺寸在上游校验后 422
    - character_id（单角色参考）→ character_ids=[...]
    - control_type 仅在同时提供 control_image_b64 时生效
    - ip_adapter_* 为 Phase C 预留：GenerationParams 扩展后落地，当前忽略

    Raises:
        ValueError: size 无法解析为宽高时抛出（上游应校验后调用）。
    """
    if body.size:
        try:
            width_s, height_s = body.size.lower().split('x')
            width, height = int(width_s), int(height_s)
        except (ValueError, TypeError) as e:
            raise ValueError(f'size 无效: {body.size!r}') from e
    else:
        width, height = 1024, 1024

    return GenerationParams(
        prompt=body.prompt,
        width=width,
        height=height,
        character_ids=[body.character_id] if body.character_id else [],
        control_type=body.control_type if (body.control_type and body.control_image_b64) else None,
        control_weight=body.control_weight,
    )


def validate_body(body: ImagesGenerationRequest) -> str | None:
    """校验 OpenAI 约束，返回错误消息（None = 通过）。

    校验项:
    - response_format 仅支持 b64_json
    - size 必须是受支持的尺寸（_SUPPORTED_SIZES）
    """
    if body.response_format and body.response_format != 'b64_json':
        return (
            f'仅支持 response_format="b64_json"（收到 {body.response_format!r}）；'
            '不支持 url'
        )
    if body.size and body.size not in _SUPPORTED_SIZES:
        return f'不支持的 size={body.size!r}；可用: {sorted(_SUPPORTED_SIZES)}'
    return None