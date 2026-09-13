"""内容推送 API — 外部系统通过此接口推送 AI 生成内容。

端点:
    POST /api/v1/content/push  — 推送单个内容片段
    POST /api/v1/content/batch — 批量推送
    GET  /api/v1/content/list  — 查询已推送内容列表
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_db_session_depends

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/content', tags=['consistency-agent'])


# =============================================================================
# 请求/响应模型
# =============================================================================


class ContentPushRequest(BaseModel):
    """内容推送请求。"""

    project_id: str = Field(..., description='项目 ID')
    content_type: str = Field(..., description="内容类型: 'novel_chapter' | 'comic_panel' | 'custom'")
    sequence_number: int = Field(..., description='序列号（章节号/分镜号）')
    title: str = Field(default='', description='标题')
    content: str = Field(default='', description='正文/脚本内容')
    metadata: dict[str, Any] = Field(default_factory=dict, description='领域特定元数据')


class ContentPushResponse(BaseModel):
    """内容推送响应。"""

    segment_id: str
    content_type: str
    sequence_number: int
    status: str = 'accepted'
    message: str = ''


class BatchPushRequest(BaseModel):
    """批量推送请求。"""

    project_id: str
    items: list[ContentPushRequest]


class ContentListResponse(BaseModel):
    """内容列表响应。"""

    segments: list[dict[str, Any]]
    total: int


# =============================================================================
# 端点
# =============================================================================


@router.post('/push', response_model=ContentPushResponse)
async def push_content(
    body: ContentPushRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """推送单个内容片段到一致性 Agent。"""
    from app.adapters import ADAPTER_REGISTRY

    # 查找适配器
    adapter = ADAPTER_REGISTRY.get(body.content_type)
    if not adapter:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 content_type: {body.content_type}，"
            f"可用类型: {list(ADAPTER_REGISTRY.keys())}",
        )

    # 校验输入
    raw = body.model_dump()
    is_valid, error_msg = adapter.validate_input(raw)
    if not is_valid:
        raise HTTPException(status_code=422, detail=f'输入校验失败: {error_msg}')

    # 转换为 ContentSegment
    segment = await adapter.ingest(raw, body.project_id, user_id)

    # 持久化
    db.add(segment)
    await db.commit()
    await db.refresh(segment)
    logger.info(
        '[CA] 内容推送成功: type=%s seq=%d project=%s',
        body.content_type,
        body.sequence_number,
        body.project_id[:8],
    )
    return ContentPushResponse(
        segment_id=segment.id,
        content_type=body.content_type,
        sequence_number=body.sequence_number,
        status='accepted',
        message=f'已接收，适配器: {type(adapter).__name__}',
    )


@router.post('/batch', response_model=list[ContentPushResponse])
async def batch_push_content(
    body: BatchPushRequest,
    request: Request,
):
    """批量推送内容片段。"""
    results = []
    for item in body.items:
        # 复用单条推送逻辑
        item.project_id = body.project_id
        try:
            result = await push_content(item, request)
            results.append(result)
        except HTTPException as e:
            results.append(
                ContentPushResponse(
                    segment_id='',
                    content_type=item.content_type,
                    sequence_number=item.sequence_number,
                    status='failed',
                    message=str(e.detail),
                )
            )
    return results


@router.get('/list', response_model=ContentListResponse)
async def list_content(
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
    project_id: str = None,
    content_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """查询已推送的内容列表。"""
    from app.models.content_segment import ContentSegment

    query = (
        select(ContentSegment)
        .where(
            ContentSegment.project_id == project_id,
            ContentSegment.user_id == user_id,
        )
        .order_by(ContentSegment.sequence_number.desc())
    )
    if content_type:
        query = query.where(ContentSegment.content_type == content_type)

    # 总数
    from sqlalchemy import func

    count_query = select(func.count()).select_from(ContentSegment).where(
        ContentSegment.project_id == project_id,
        ContentSegment.user_id == user_id,
    )
    if content_type:
        count_query = count_query.where(ContentSegment.content_type == content_type)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    segments = []
    for seg in result.scalars().all():
        segments.append(
            {
                'id': seg.id,
                'content_type': seg.content_type,
                'sequence_number': seg.sequence_number,
                'title': seg.title,
                'content_length': len(seg.content or ''),
                'created_at': str(seg.created_at or ''),
            }
        )
    return ContentListResponse(segments=segments, total=total)
