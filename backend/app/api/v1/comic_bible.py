"""设定圣经 + 角色卡 + 画风卡 + 负面词库 + 集数 API。

端点:
    POST   /api/v1/comic/bibles              — 创建设定圣经
    GET    /api/v1/comic/bibles/{bible_id}   — 获取圣经详情
    PUT    /api/v1/comic/bibles/{bible_id}   — 更新圣经

    POST   /api/v1/comic/characters          — 创建角色卡
    GET    /api/v1/comic/characters          — 列表
    PUT    /api/v1/comic/characters/{id}     — 更新角色卡
    POST   /api/v1/comic/characters/{id}/lock — 锁定角色卡

    POST   /api/v1/comic/styles              — 创建画风卡
    GET    /api/v1/comic/styles/{project_id} — 获取项目画风

    POST   /api/v1/comic/negative-prompts    — 创建/更新负面词库
    GET    /api/v1/comic/negative-prompts/{project_id} — 获取负面词库

    POST   /api/v1/comic/episodes            — 创建集数
    GET    /api/v1/comic/episodes            — 集数列表
    PUT    /api/v1/comic/episodes/{id}       — 更新集数
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_db_session_depends
from app.core.exceptions import NotFoundError, ConflictError
from app.models.comic_bible import (
    SettingBible, CharacterCard, ArtStyleCard,
    NegativePromptLibrary, ComicEpisode,
)

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/comic', tags=['comic-production'])


# =============================================================================
# 请求/响应模型
# =============================================================================

class BibleCreateRequest(BaseModel):
    project_id: str
    world_name: str = Field(..., description='世界观名称')
    summary: str = ''
    time_period: str = ''
    location_rules: dict | list = Field(default_factory=dict)
    magic_system: dict | list = Field(default_factory=dict)
    tone: str = ''
    extra: dict | list = Field(default_factory=dict)


class BibleUpdateRequest(BaseModel):
    world_name: str | None = None
    summary: str | None = None
    time_period: str | None = None
    location_rules: dict | list | None = None
    magic_system: dict | list | None = None
    tone: str | None = None
    extra: dict | list | None = None


class CharacterCreateRequest(BaseModel):
    project_id: str
    bible_id: str | None = None
    name: str = Field(..., description='角色姓名')
    age: str = ''
    gender: str = ''
    hair: str = ''
    eyes: str = ''
    outfit: str = ''
    accessories: list[str] = Field(default_factory=list)
    personality: str = ''
    catchphrase: str = ''
    voice_timbre: str = ''
    appearance_prompt: str = ''
    reference_images: list[str] = Field(default_factory=list)
    negative_traits: list[str] = Field(default_factory=list)


class CharacterUpdateRequest(BaseModel):
    name: str | None = None
    age: str | None = None
    gender: str | None = None
    hair: str | None = None
    eyes: str | None = None
    outfit: str | None = None
    accessories: list[str] | None = None
    personality: str | None = None
    catchphrase: str | None = None
    voice_timbre: str | None = None
    appearance_prompt: str | None = None
    reference_images: list[str] | None = None
    negative_traits: list[str] | None = None


class StyleCreateRequest(BaseModel):
    project_id: str
    style_name: str = Field(..., description='画风名称（日系赛璐璐/国漫/厚涂等）')
    color_palette: list[str] = Field(default_factory=list)
    line_style: str = ''
    lighting: str = ''
    base_prompt: str = ''
    negative_prompt: str = ''
    seed: int | None = None
    reference_images: list[str] = Field(default_factory=list)


class NegativePromptRequest(BaseModel):
    project_id: str
    category: str = Field(default='universal', description='universal/character/scene')
    prompts: list[str] = Field(default_factory=list)


class EpisodeCreateRequest(BaseModel):
    project_id: str
    episode_number: int
    title: str = ''
    summary: str = ''
    next_hook: str = ''


class EpisodeUpdateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    next_hook: str | None = None
    status: str | None = None


# =============================================================================
# 辅助函数
# =============================================================================

def _model_to_dict(obj, extra_fields: dict | None = None) -> dict:
    """SQLAlchemy 模型转 dict。"""
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name, None)
        result[col.name] = val
    if extra_fields:
        result.update(extra_fields)
    return result


# =============================================================================
# 设定圣经 API
# =============================================================================

@router.post('/bibles')
async def create_bible(
    req: BibleCreateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """创建设定圣经。"""
    bible = SettingBible(
        project_id=req.project_id,
        user_id=user_id,
        world_name=req.world_name,
        summary=req.summary,
        time_period=req.time_period,
        location_rules=req.location_rules,
        magic_system=req.magic_system,
        tone=req.tone,
        extra=req.extra,
    )
    db.add(bible)
    await db.commit()
    await db.refresh(bible)
    return {'id': bible.id, 'world_name': bible.world_name, 'status': 'created'}


@router.get('/bibles/{bible_id}')
async def get_bible(
    bible_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """获取设定圣经详情。"""
    result = await db.execute(
        select(SettingBible).where(SettingBible.id == bible_id)
    )
    bible = result.scalar_one_or_none()
    if not bible:
        raise NotFoundError('圣经', bible_id)
    data = _model_to_dict(bible)
    # 附带角色卡列表
    chars_result = await db.execute(
        select(CharacterCard).where(CharacterCard.bible_id == bible_id)
    )
    chars = chars_result.scalars().all()
    data['characters'] = [_model_to_dict(c) for c in chars]
    return data


@router.put('/bibles/{bible_id}')
async def update_bible(
    bible_id: str,
    req: BibleUpdateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """更新设定圣经。"""
    result = await db.execute(
        select(SettingBible).where(SettingBible.id == bible_id)
    )
    bible = result.scalar_one_or_none()
    if not bible:
        raise NotFoundError('圣经', bible_id)
    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(bible, key, value)
    await db.commit()
    return {'id': bible.id, 'status': 'updated'}


# =============================================================================
# 角色卡 API
# =============================================================================

@router.post('/characters')
async def create_character(
    req: CharacterCreateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """创建角色卡。"""
    char = CharacterCard(
        project_id=req.project_id,
        user_id=user_id,
        bible_id=req.bible_id,
        name=req.name,
        age=req.age,
        gender=req.gender,
        hair=req.hair,
        eyes=req.eyes,
        outfit=req.outfit,
        accessories=req.accessories,
        personality=req.personality,
        catchphrase=req.catchphrase,
        voice_timbre=req.voice_timbre,
        appearance_prompt=req.appearance_prompt,
        reference_images=req.reference_images,
        negative_traits=req.negative_traits,
    )
    db.add(char)
    await db.commit()
    await db.refresh(char)
    return {'id': char.id, 'name': char.name, 'status': char.status}


@router.get('/characters')
async def list_characters(
    project_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """列出项目下所有角色卡。"""
    result = await db.execute(
        select(CharacterCard)
        .where(CharacterCard.project_id == project_id)
        .order_by(CharacterCard.created_at)
    )
    chars = result.scalars().all()
    return {'characters': [_model_to_dict(c) for c in chars], 'total': len(chars)}


@router.put('/characters/{char_id}')
async def update_character(
    char_id: str,
    req: CharacterUpdateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """更新角色卡。"""
    result = await db.execute(
        select(CharacterCard).where(CharacterCard.id == char_id)
    )
    char = result.scalar_one_or_none()
    if not char:
        raise NotFoundError('角色卡', char_id)
    if char.status == 'locked':
        raise ConflictError('角色卡已锁定，请先解锁')
    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(char, key, value)
    await db.commit()
    return {'id': char.id, 'name': char.name, 'status': 'updated'}


@router.post('/characters/{char_id}/lock')
async def lock_character(
    char_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """锁定/解锁角色卡（定稿）。"""
    result = await db.execute(
        select(CharacterCard).where(CharacterCard.id == char_id)
    )
    char = result.scalar_one_or_none()
    if not char:
        raise NotFoundError('角色卡', char_id)
    # toggle: locked → approved, 其他 → locked
    char.status = 'approved' if char.status == 'locked' else 'locked'
    await db.commit()
    return {'id': char.id, 'name': char.name, 'status': char.status}


# =============================================================================
# 画风卡 API
# =============================================================================

@router.post('/styles')
async def create_style(
    req: StyleCreateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """创建画风卡。"""
    style = ArtStyleCard(
        project_id=req.project_id,
        user_id=user_id,
        style_name=req.style_name,
        color_palette=req.color_palette,
        line_style=req.line_style,
        lighting=req.lighting,
        base_prompt=req.base_prompt,
        negative_prompt=req.negative_prompt,
        seed=req.seed,
        reference_images=req.reference_images,
    )
    db.add(style)
    await db.commit()
    await db.refresh(style)
    return {'id': style.id, 'style_name': style.style_name, 'status': 'created'}


@router.get('/styles/{project_id}')
async def get_style(
    project_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """获取项目画风卡。"""
    result = await db.execute(
        select(ArtStyleCard)
        .where(ArtStyleCard.project_id == project_id)
        .order_by(ArtStyleCard.created_at.desc())
        .limit(1)
    )
    style = result.scalar_one_or_none()
    if not style:
        return {'style': None, 'message': '未设置画风'}
    return _model_to_dict(style)


# =============================================================================
# 负面词库 API
# =============================================================================

@router.post('/negative-prompts')
async def upsert_negative_prompts(
    req: NegativePromptRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """创建或更新负面词库。"""
    result = await db.execute(
        select(NegativePromptLibrary).where(
            NegativePromptLibrary.project_id == req.project_id,
            NegativePromptLibrary.category == req.category,
        )
    )
    lib = result.scalar_one_or_none()
    if lib:
        lib.prompts = req.prompts
    else:
        lib = NegativePromptLibrary(
            project_id=req.project_id,
            user_id=user_id,
            category=req.category,
            prompts=req.prompts,
        )
        db.add(lib)
    await db.commit()
    return {'status': 'saved', 'category': req.category, 'count': len(req.prompts)}


@router.get('/negative-prompts/{project_id}')
async def get_negative_prompts(
    project_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """获取项目负面词库。"""
    result = await db.execute(
        select(NegativePromptLibrary)
        .where(NegativePromptLibrary.project_id == project_id)
    )
    libs = result.scalars().all()
    return {
        'libraries': [_model_to_dict(lib) for lib in libs],
        'total': len(libs),
    }


# =============================================================================
# 集数 API
# =============================================================================

@router.post('/episodes')
async def create_episode(
    req: EpisodeCreateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """创建集数。"""
    ep = ComicEpisode(
        project_id=req.project_id,
        user_id=user_id,
        episode_number=req.episode_number,
        title=req.title,
        summary=req.summary,
        next_hook=req.next_hook,
    )
    db.add(ep)
    await db.commit()
    await db.refresh(ep)
    return {'id': ep.id, 'episode_number': ep.episode_number, 'status': ep.status}


@router.get('/episodes')
async def list_episodes(
    project_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """列出项目下所有集数。"""
    result = await db.execute(
        select(ComicEpisode)
        .where(ComicEpisode.project_id == project_id)
        .order_by(ComicEpisode.episode_number)
    )
    eps = result.scalars().all()
    return {'episodes': [_model_to_dict(e) for e in eps], 'total': len(eps)}


@router.put('/episodes/{episode_id}')
async def update_episode(
    episode_id: str,
    req: EpisodeUpdateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """更新集数。"""
    result = await db.execute(
        select(ComicEpisode).where(ComicEpisode.id == episode_id)
    )
    ep = result.scalar_one_or_none()
    if not ep:
        raise NotFoundError('集数', episode_id)
    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(ep, key, value)
    await db.commit()
    return {'id': ep.id, 'status': 'updated'}
