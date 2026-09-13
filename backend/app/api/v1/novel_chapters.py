"""小说章节 CRUD API。

端点:
    GET    /api/v1/novel/chapters?project_id=xxx  — 章节列表
    POST   /api/v1/novel/chapters                 — 创建章节
    GET    /api/v1/novel/chapters/{id}            — 章节详情
    PUT    /api/v1/novel/chapters/{id}            — 更新章节
    DELETE /api/v1/novel/chapters/{id}            — 删除章节
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_db_session_depends
from app.models.chapter import Chapter

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/novel', tags=['novel'])


# =============================================================================
# 请求/响应模型
# =============================================================================

class ChapterCreateRequest(BaseModel):
    project_id: str
    chapter_number: int = Field(..., ge=1, description='章节序号')
    title: str = Field(..., min_length=1, max_length=200)
    content: str = ''
    summary: str = ''


class ChapterUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    summary: str | None = None


def _chapter_to_dict(ch: Chapter) -> dict:
    return {
        'id': ch.id,
        'project_id': ch.project_id,
        'chapter_number': ch.chapter_number,
        'title': ch.title,
        'content': ch.content or '',
        'summary': ch.summary or '',
        'word_count': ch.word_count or 0,
        'status': ch.status or 'draft',
        'outline_id': ch.outline_id,
        'expansion_plan': ch.expansion_plan,
        'created_at': ch.created_at.isoformat() if ch.created_at else None,
        'updated_at': ch.updated_at.isoformat() if ch.updated_at else None,
    }


# =============================================================================
# GET /api/v1/novel/chapters — 章节列表
# =============================================================================

@router.get('/chapters')
async def list_chapters(
    project_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """获取项目的章节列表（按 chapter_number 排序）。"""
    query = (
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_number)
    )
    result = await db.execute(query)
    chapters = result.scalars().all()

    count_query = (
        select(func.count())
        .select_from(Chapter)
        .where(Chapter.project_id == project_id)
    )
    total = (await db.execute(count_query)).scalar() or 0

    return {
        'chapters': [_chapter_to_dict(ch) for ch in chapters],
        'total': total,
    }


# =============================================================================
# POST /api/v1/novel/chapters — 创建章节
# =============================================================================

@router.post('/chapters')
async def create_chapter(
    req: ChapterCreateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """创建新章节。"""
    # 检查序号是否已存在
    existing = await db.execute(
        select(Chapter).where(
            Chapter.project_id == req.project_id,
            Chapter.chapter_number == req.chapter_number,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f'第 {req.chapter_number} 章已存在',
        )

    chapter = Chapter(
        id=str(uuid.uuid4()),
        project_id=req.project_id,
        chapter_number=req.chapter_number,
        title=req.title,
        content=req.content,
        summary=req.summary,
        word_count=len(req.content),
        status='draft',
    )
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)

    logger.info('[Novel] 创建章节: project=%s ch=%d title=%s', req.project_id[:8], req.chapter_number, req.title)
    return _chapter_to_dict(chapter)


# =============================================================================
# GET /api/v1/novel/chapters/{id} — 章节详情
# =============================================================================

@router.get('/chapters/{chapter_id}')
async def get_chapter(
    chapter_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """获取章节详情（含完整 content）。"""
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail='章节不存在')
    return _chapter_to_dict(chapter)


# =============================================================================
# PUT /api/v1/novel/chapters/{id} — 更新章节
# =============================================================================

@router.put('/chapters/{chapter_id}')
async def update_chapter(
    chapter_id: str,
    req: ChapterUpdateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """更新章节内容。"""
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail='章节不存在')

    if req.title is not None:
        chapter.title = req.title
    if req.content is not None:
        chapter.content = req.content
        chapter.word_count = len(req.content)
    if req.summary is not None:
        chapter.summary = req.summary

    await db.commit()
    await db.refresh(chapter)

    logger.info('[Novel] 更新章节: %s', chapter_id[:8])
    return _chapter_to_dict(chapter)


# =============================================================================
# DELETE /api/v1/novel/chapters/{id} — 删除章节
# =============================================================================

@router.delete('/chapters/{chapter_id}')
async def delete_chapter(
    chapter_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """删除章节。"""
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail='章节不存在')

    await db.delete(chapter)
    await db.commit()

    logger.info('[Novel] 删除章节: %s', chapter_id[:8])
    return {'ok': True}
