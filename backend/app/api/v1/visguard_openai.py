"""VisGuard OpenAI 兼容路由（内嵌 WLai 平台）。

端点:
    POST /api/v1/visguard/openai/images/generations — OpenAI 兼容生图（同步等待）
    POST /api/v1/visguard/openai/chat/completions   — 501（Phase 2）
    POST /api/v1/visguard/openai/embeddings         — 501（Phase 2）
    GET  /api/v1/visguard/openai/models             — 501（Phase 2）

设计（P0-5）:
- schema 严格对齐 OpenAI（请求/响应模型见 services/visguard/openai_compat/）；
- 同步等待生图完成（内部超时机制在生图后端落地时实现）；
- 错误统一 OpenAI error 形状（detail 透传由 main.py handler 完成）；
- 认证复用 WLai JWT（get_current_user_id），与平台一致。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_db_session_depends
from app.api.v1.visguard import _owned_project
from app.services.visguard.core.exceptions import BackendNotConfiguredError, VisGuardError
from app.services.visguard.generation.factory import create_generator
from app.services.visguard.openai_compat.images import (
    ImageData,
    ImagesGenerationRequest,
    ImagesGenerationResponse,
    openai_error_detail,
    to_visguard_params,
    validate_body,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/visguard/openai', tags=['visguard-openai'])


# =============================================================================
# POST /images/generations — OpenAI 兼容生图（同步等待）
# =============================================================================


@router.post('/images/generations', include_in_schema=False)
async def images_generations(
    body: ImagesGenerationRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """OpenAI 兼容生图 — 同步等待结果（Phase C 落地真实云端适配）。"""
    await _owned_project(body.project_id, db, user_id)

    # 参数约束（OpenAI 语义）：response_format / size 白名单
    if err := validate_body(body):
        raise HTTPException(
            status_code=422, detail=openai_error_detail(err, code='invalid_size_or_format'),
        )

    generator = create_generator()
    if generator is None:
        raise HTTPException(
            status_code=501,
            detail=openai_error_detail(
                '生图功能未启用（VisGuard 未配置云端模式）',
                error_type='invalid_request_error',
                code='generate_not_available',
            ),
        )

    try:
        params = to_visguard_params(body)
        result = await generator.generate(params)
    except BackendNotConfiguredError as e:
        # 生图后端尚在 Phase C 落地，兼容契约已就绪但无法出图
        raise HTTPException(
            status_code=501,
            detail=openai_error_detail(
                str(e), error_type='invalid_request_error', code='not_implemented',
            ),
        ) from e
    except VisGuardError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=openai_error_detail(str(e), error_type='invalid_request_error', code=e.code),
        ) from e
    except Exception as e:  # noqa: BLE001 - 供应商错误统一归一（不泄漏堆栈细节）
        logger.error('[VisGuard] OpenAI 兼容生图失败: %s', e)
        raise HTTPException(
            status_code=500,
            detail=openai_error_detail(
                '生图执行失败，请稍后重试', error_type='server_error', code='internal_error',
            ),
        ) from e

    b64 = next(
        (a.to_b64() for a in result.artifacts if a.to_b64() is not None),
        None,
    )
    if b64 is None:
        raise HTTPException(
            status_code=500,
            detail=openai_error_detail(
                '生成结果缺少图片数据', error_type='server_error', code='empty_result',
            ),
        )

    return ImagesGenerationResponse(
        data=[ImageData(b64_json=b64, revised_prompt=body.prompt)],
    )


# =============================================================================
# 501 Not Implemented（Phase 2 落地前明确拒绝）
# =============================================================================


_NOT_IMPLEMENTED_DETAIL = openai_error_detail(
    '该接口尚未实现（Phase 2）', error_type='invalid_request_error', code='not_implemented',
)


@router.post('/chat/completions', include_in_schema=False)
async def chat_completions():
    """Chat Completions — Phase 2 实现，当前 501（含 stream=true 同路径）。"""
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)


@router.post('/embeddings', include_in_schema=False)
async def embeddings():
    """Embeddings — Phase 2 实现，当前 501。"""
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)


@router.get('/models', include_in_schema=False)
async def models():
    """Models 列表 — Phase 2 实现，当前 501。"""
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)