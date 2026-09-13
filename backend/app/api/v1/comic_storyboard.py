"""分镜 + 镜头 + 素材 + 审核 API。

端点:
    POST   /api/v1/comic/storyboards/generate — 从文本生成分镜
    GET    /api/v1/comic/storyboards/{id}     — 获取分镜表
    PUT    /api/v1/comic/storyboards/{id}     — 编辑分镜
    POST   /api/v1/comic/storyboards/{id}/confirm — 确认分镜

    GET    /api/v1/comic/shots               — 镜头列表
    PUT    /api/v1/comic/shots/{id}/status    — 状态流转
    POST   /api/v1/comic/shots/{id}/compile   — 编译提示词

    POST   /api/v1/comic/assets              — 上传/注册素材
    GET    /api/v1/comic/assets              — 素材列表

    POST   /api/v1/comic/reviews             — 创建审核点
    PUT    /api/v1/comic/reviews/{id}         — 提交审核结果
    GET    /api/v1/comic/reviews             — 待审核列表
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_db_session_depends
from app.core.exceptions import NotFoundError, ValidationError
from app.models.comic_bible import (
    SettingBible, CharacterCard, ArtStyleCard,
    NegativePromptLibrary, ComicEpisode,
)
from app.models.comic_shot import Storyboard, Shot, ShotAsset
from app.models.comic_review import ReviewCheckpoint
from app.services.comic.storyboard_gen import StoryboardGenerator
from app.services.comic.prompt_compiler import PromptCompiler
from app.services.comic.shot_state_machine import ShotStateMachine

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/comic', tags=['comic-production'])


# =============================================================================
# 请求/响应模型
# =============================================================================

class StoryboardGenerateRequest(BaseModel):
    project_id: str
    episode_id: str | None = None
    text: str = Field(..., description='原始小说/故事文本')
    character_names: list[str] = Field(default_factory=list, description='已知角色名')


class StoryboardUpdateRequest(BaseModel):
    title: str | None = None
    status: str | None = None


class ShotStatusRequest(BaseModel):
    target_status: str = Field(..., description='目标状态')


class ShotCompileRequest(BaseModel):
    platform: str = Field(default='midjourney', description='目标平台: midjourney/stable_diffusion/jimeng/kling')


class AssetCreateRequest(BaseModel):
    shot_id: str
    project_id: str
    asset_type: str = Field(..., description='image/video/voice/subtitle/bgm')
    file_url: str = ''
    prompt_used: str = ''
    parameters: dict | list = Field(default_factory=dict)
    naming: str = ''


class ReviewCreateRequest(BaseModel):
    project_id: str
    target_type: str = Field(..., description='character_card/storyboard/shot/episode')
    target_id: str
    review_type: str = Field(..., description='character_design/storyboard_confirm/first_frame/video_confirm/final_cut')


class ReviewUpdateRequest(BaseModel):
    status: str = Field(..., description='approved/rejected/revision_requested')
    reviewer_notes: str = ''
    reviewed_by: str = ''


# =============================================================================
# 辅助函数
# =============================================================================

def _model_to_dict(obj) -> dict:
    """SQLAlchemy 模型转 dict。"""
    return {col.name: getattr(obj, col.name, None) for col in obj.__table__.columns}


# =============================================================================
# 分镜 API
# =============================================================================

@router.post('/storyboards/generate')
async def generate_storyboard(
    req: StoryboardGenerateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """从文本自动生成分镜表。"""
    gen = StoryboardGenerator()
    result = await gen.generate_from_text(
        text=req.text,
        project_id=req.project_id,
        user_id=user_id,
        episode_id=req.episode_id,
        character_names=req.character_names,
    )

    sb_data = result['storyboard']
    shots_data = result['shots']

    # 创建分镜表记录
    storyboard = Storyboard(
        id=sb_data['id'],
        project_id=req.project_id,
        user_id=user_id,
        episode_id=req.episode_id,
        title=sb_data['title'],
        source_text=sb_data['source_text'],
        shot_count=sb_data['shot_count'],
        status='draft',
    )
    db.add(storyboard)

    # 创建镜头记录
    for shot_data in shots_data:
        matched = shot_data.pop('matched_characters', [])
        metadata = shot_data.pop('metadata', {})
        shot = Shot(
            project_id=req.project_id,
            user_id=user_id,
            storyboard_id=storyboard.id,
            episode_id=req.episode_id,
            shot_number=shot_data['shot_number'],
            duration=shot_data['duration'],
            scene_type=shot_data['scene_type'],
            visual_description=shot_data['visual_description'],
            character_action=shot_data['character_action'],
            dialogue=shot_data['dialogue'],
            sound_effect=shot_data['sound_effect'],
            camera_movement=shot_data['camera_movement'],
            status=shot_data['status'],
            metadata_json={'matched_characters': matched, **metadata},
        )
        db.add(shot)

    await db.commit()
    await db.refresh(storyboard)

    return {
        'storyboard_id': storyboard.id,
        'shot_count': storyboard.shot_count,
        'status': storyboard.status,
        'shots': [
            {
                'shot_number': s.shot_number,
                'scene_type': s.scene_type,
                'visual_description': s.visual_description[:80],
                'dialogue': s.dialogue,
                'status': s.status,
            }
            for s in (
                await db.execute(
                    select(Shot)
                    .where(Shot.storyboard_id == storyboard.id)
                    .order_by(Shot.shot_number)
                )
            ).scalars().all()
        ],
    }


@router.get('/storyboards/{storyboard_id}')
async def get_storyboard(
    storyboard_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """获取分镜表详情（含镜头列表）。"""
    result = await db.execute(
        select(Storyboard).where(Storyboard.id == storyboard_id)
    )
    sb = result.scalar_one_or_none()
    if not sb:
        raise NotFoundError('分镜表', storyboard_id)

    data = _model_to_dict(sb)

    shots_result = await db.execute(
        select(Shot)
        .where(Shot.storyboard_id == storyboard_id)
        .order_by(Shot.shot_number)
    )
    shots = shots_result.scalars().all()
    data['shots'] = [_model_to_dict(s) for s in shots]
    return data


@router.put('/storyboards/{storyboard_id}')
async def update_storyboard(
    storyboard_id: str,
    req: StoryboardUpdateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """编辑分镜表。"""
    result = await db.execute(
        select(Storyboard).where(Storyboard.id == storyboard_id)
    )
    sb = result.scalar_one_or_none()
    if not sb:
        raise NotFoundError('分镜表', storyboard_id)
    if req.title is not None:
        sb.title = req.title
    if req.status is not None:
        sb.status = req.status
    await db.commit()
    return {'id': sb.id, 'status': 'updated'}


@router.post('/storyboards/{storyboard_id}/confirm')
async def confirm_storyboard(
    storyboard_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """确认分镜表。"""
    result = await db.execute(
        select(Storyboard).where(Storyboard.id == storyboard_id)
    )
    sb = result.scalar_one_or_none()
    if not sb:
        raise NotFoundError('分镜表', storyboard_id)
    sb.status = 'confirmed'
    # 将所有镜头状态推进到 pending_image
    shots_result = await db.execute(
        select(Shot).where(
            Shot.storyboard_id == storyboard_id,
            Shot.status == 'pending_script',
        )
    )
    sm = ShotStateMachine()
    for shot in shots_result.scalars().all():
        try:
            shot.status = sm.transition(shot.status, 'pending_image')
        except ValueError:
            pass  # 已不在 pending_script 的跳过
    await db.commit()
    return {'id': sb.id, 'status': 'confirmed', 'message': '分镜已确认，镜头进入出图阶段'}


# =============================================================================
# 镜头 API
# =============================================================================

@router.get('/shots')
async def list_shots(
    storyboard_id: str = None,
    project_id: str = None,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """列出分镜表下所有镜头，或按项目查询全部镜头。"""
    if project_id:
        result = await db.execute(
            select(Shot)
            .where(Shot.project_id == project_id)
            .order_by(Shot.shot_number)
        )
    elif storyboard_id:
        result = await db.execute(
            select(Shot)
            .where(Shot.storyboard_id == storyboard_id)
            .order_by(Shot.shot_number)
        )
    else:
        return {'shots': [], 'total': 0}
    shots = result.scalars().all()
    return {
        'shots': [_model_to_dict(s) for s in shots],
        'total': len(shots),
    }


@router.put('/shots/{shot_id}/status')
async def update_shot_status(
    shot_id: str,
    req: ShotStatusRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """镜头状态流转。"""
    result = await db.execute(
        select(Shot).where(Shot.id == shot_id)
    )
    shot = result.scalar_one_or_none()
    if not shot:
        raise NotFoundError('镜头', shot_id)

    sm = ShotStateMachine()
    try:
        new_status = sm.transition(shot.status, req.target_status)
    except ValueError as e:
        raise ValidationError(str(e))

    shot.status = new_status
    await db.commit()
    return {
        'id': shot.id,
        'shot_number': shot.shot_number,
        'previous_status': shot.status,
        'current_status': new_status,
        'label': sm.get_label(new_status),
    }


@router.post('/shots/{shot_id}/compile')
async def compile_shot_prompt(
    shot_id: str,
    req: ShotCompileRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """编译单镜头提示词。"""
    # 获取镜头数据
    shot_result = await db.execute(
        select(Shot).where(Shot.id == shot_id)
    )
    shot = shot_result.scalar_one_or_none()
    if not shot:
        raise NotFoundError('镜头', shot_id)

    shot_dict = _model_to_dict(shot)

    # 获取画风卡
    style_result = await db.execute(
        select(ArtStyleCard)
        .where(ArtStyleCard.project_id == shot.project_id)
        .order_by(ArtStyleCard.created_at.desc())
        .limit(1)
    )
    style = style_result.scalar_one_or_none()
    style_dict = _model_to_dict(style) if style else {}

    # 获取匹配的角色卡（从 metadata 中读取）
    matched_names = []
    if shot.metadata_json and isinstance(shot.metadata_json, dict):
        matched_names = shot.metadata_json.get('matched_characters', [])

    char_dicts = []
    if matched_names:
        chars_result = await db.execute(
            select(CharacterCard).where(
                CharacterCard.project_id == shot.project_id,
                CharacterCard.name.in_(matched_names),
            )
        )
        char_dicts = [_model_to_dict(c) for c in chars_result.scalars().all()]

    # 获取负面词库
    neg_result = await db.execute(
        select(NegativePromptLibrary).where(
            NegativePromptLibrary.project_id == shot.project_id,
            NegativePromptLibrary.category == 'universal',
        )
    )
    neg_lib = neg_result.scalar_one_or_none()
    neg_dict = _model_to_dict(neg_lib) if neg_lib else None

    # 编译
    compiler = PromptCompiler()
    compiled = await compiler.compile_shot_prompt(
        shot=shot_dict,
        character_cards=char_dicts,
        style=style_dict,
        negative_lib=neg_dict,
    )

    # 适配平台格式
    platform_prompt = await compiler.compile_for_platform(compiled, req.platform)

    # 保存编译结果到镜头
    shot.compiled_prompt = platform_prompt
    if compiled.get('seed'):
        shot.seed = compiled['seed']
    await db.commit()

    return {
        'shot_id': shot.id,
        'shot_number': shot.shot_number,
        'compiled': compiled,
        'platform_prompt': platform_prompt,
        'platform': req.platform,
    }


# =============================================================================
# 素材 API
# =============================================================================

@router.post('/assets')
async def create_asset(
    req: AssetCreateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """上传/注册素材。"""
    # 计算版本号
    existing = await db.execute(
        select(ShotAsset).where(
            ShotAsset.shot_id == req.shot_id,
            ShotAsset.asset_type == req.asset_type,
        )
    )
    version = len(existing.scalars().all()) + 1

    asset = ShotAsset(
        project_id=req.project_id,
        user_id=user_id,
        shot_id=req.shot_id,
        asset_type=req.asset_type,
        version=version,
        file_url=req.file_url,
        prompt_used=req.prompt_used,
        parameters=req.parameters,
        status='passed',
        naming=req.naming or f'v{version}',
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return {'id': asset.id, 'version': version, 'status': 'created'}


@router.get('/assets')
async def list_assets(
    shot_id: str,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """列出镜头下所有素材。"""
    result = await db.execute(
        select(ShotAsset)
        .where(ShotAsset.shot_id == shot_id)
        .order_by(ShotAsset.asset_type, ShotAsset.version)
    )
    assets = result.scalars().all()
    return {
        'assets': [_model_to_dict(a) for a in assets],
        'total': len(assets),
    }


# =============================================================================
# 审核 API
# =============================================================================

@router.post('/reviews')
async def create_review(
    req: ReviewCreateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """创建审核点。"""
    review = ReviewCheckpoint(
        project_id=req.project_id,
        user_id=user_id,
        target_type=req.target_type,
        target_id=req.target_id,
        review_type=req.review_type,
        status='pending',
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return {
        'id': review.id,
        'target_type': review.target_type,
        'review_type': review.review_type,
        'status': 'pending',
    }


@router.put('/reviews/{review_id}')
async def update_review(
    review_id: str,
    req: ReviewUpdateRequest,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """提交审核结果。"""
    result = await db.execute(
        select(ReviewCheckpoint).where(ReviewCheckpoint.id == review_id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise NotFoundError('审核点', review_id)

    review.status = req.status
    review.reviewer_notes = req.reviewer_notes
    review.reviewed_by = req.reviewed_by
    review.reviewed_at = datetime.now(tz=timezone.utc)
    await db.commit()
    return {
        'id': review.id,
        'status': review.status,
        'reviewed_at': review.reviewed_at.isoformat() if review.reviewed_at else None,
    }


@router.get('/reviews')
async def list_reviews(
    project_id: str,
    status: str = 'pending',
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """列出待审核项。"""
    result = await db.execute(
        select(ReviewCheckpoint)
        .where(
            ReviewCheckpoint.project_id == project_id,
            ReviewCheckpoint.status == status,
        )
        .order_by(ReviewCheckpoint.created_at)
    )
    reviews = result.scalars().all()
    return {
        'reviews': [_model_to_dict(r) for r in reviews],
        'total': len(reviews),
    }
