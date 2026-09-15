"""项目 CRUD 路由

路由前缀: /api/projects
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/projects', tags=['Projects'])


# ── 请求/响应模型 ──────────────────────────────────────────────


class ProjectResponse(BaseModel):
    id: str
    user_id: str
    title: str
    description: str | None
    theme: str | None
    genre: str | None
    target_words: int
    current_words: int
    status: str
    chapter_count: int | None
    narrative_perspective: str | None
    character_count: int | None
    cover_image_url: str | None
    cover_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]


class CreateProjectRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    genre: str | None = None
    target_words: int = 0
    theme: str | None = None


class UpdateProjectRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    genre: str | None = None
    target_words: int | None = None
    theme: str | None = None
    status: str | None = None


# ── 辅助函数 ──────────────────────────────────────────────────


def _get_user_id(request: Request) -> str:
    """从请求上下文中获取当前用户 ID。"""
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail='未认证')
    return user_id


async def _get_project_or_404(db: AsyncSession, project_id: str, user_id: str) -> Project:
    """按 ID + 归属查询项目，不存在或不属于当前用户返回 404。"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail='项目不存在')
    return project


# ── 路由 ───────────────────────────────────────────────────────


@router.get('', response_model=ProjectListResponse)
async def list_projects(request: Request, db: AsyncSession = Depends(get_db)):
    """获取当前用户的全部项目列表。"""
    user_id = _get_user_id(request)
    result = await db.execute(
        select(Project)
        .where(Project.user_id == user_id)
        .order_by(Project.updated_at.desc())
    )
    projects = result.scalars().all()
    return ProjectListResponse(projects=projects)


@router.post('', response_model=ProjectResponse, status_code=201)
async def create_project(
    request: Request,
    body: CreateProjectRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建新项目。"""
    user_id = _get_user_id(request)
    project = Project(
        user_id=user_id,
        title=body.title,
        description=body.description,
        genre=body.genre,
        target_words=body.target_words,
        theme=body.theme,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get('/{project_id}', response_model=ProjectResponse)
async def get_project(
    request: Request,
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单个项目详情。"""
    user_id = _get_user_id(request)
    project = await _get_project_or_404(db, project_id, user_id)
    return project


@router.put('/{project_id}', response_model=ProjectResponse)
async def update_project(
    request: Request,
    project_id: str,
    body: UpdateProjectRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新项目信息。"""
    user_id = _get_user_id(request)
    project = await _get_project_or_404(db, project_id, user_id)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)

    await db.commit()
    await db.refresh(project)
    return project


@router.delete('/{project_id}', status_code=204)
async def delete_project(
    request: Request,
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除项目。"""
    user_id = _get_user_id(request)
    project = await _get_project_or_404(db, project_id, user_id)
    await db.delete(project)
    await db.commit()