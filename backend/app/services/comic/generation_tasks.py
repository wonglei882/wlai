"""漫剧生成任务 — 供任务队列异步执行。

将出图流程从 API 层抽出，便于后台任务 / Demo 脚本 / 未来重试机制复用。
"""

import logging

from sqlalchemy import select

from app.database import _get_or_create_session_maker, get_engine
from app.models.comic_bible import ArtStyleCard, CharacterCard, NegativePromptLibrary
from app.models.comic_shot import Shot, ShotAsset
from app.services.comic.consistency_guardian import get_comic_guardian
from app.services.comic.prompt_compiler import PromptCompiler
from app.services.generators import get_image_generator

logger = logging.getLogger(__name__)


async def _run_image_generation(
    shot_id: str,
    user_id: str,
    platform: str = 'midjourney',
    provider: str = 'mock',
) -> dict:
    """异步执行单镜头出图任务，返回结果 dict。"""
    from app.api.v1.comic_storyboard import _model_to_dict, _write_gate_diagnostics

    engine = await get_engine()
    SessionLocal = _get_or_create_session_maker(engine)
    async with SessionLocal() as db:
        shot = (await db.execute(
            select(Shot).where(Shot.id == shot_id)
        )).scalar_one_or_none()
        if not shot:
            return {'error': f'镜头不存在: {shot_id}'}
        shot_dict = _model_to_dict(shot)

        style = (await db.execute(
            select(ArtStyleCard)
            .where(ArtStyleCard.project_id == shot.project_id)
            .order_by(ArtStyleCard.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        style_dict = _model_to_dict(style) if style else {}

        matched_names = []
        if shot.metadata_json and isinstance(shot.metadata_json, dict):
            matched_names = shot.metadata_json.get('matched_characters', [])
        char_dicts = []
        if matched_names:
            chars = (await db.execute(
                select(CharacterCard).where(
                    CharacterCard.project_id == shot.project_id,
                    CharacterCard.name.in_(matched_names),
                )
            )).scalars().all()
            char_dicts = [_model_to_dict(c) for c in chars]

        neg = (await db.execute(
            select(NegativePromptLibrary).where(
                NegativePromptLibrary.project_id == shot.project_id,
                NegativePromptLibrary.category == 'universal',
            )
        )).scalar_one_or_none()
        neg_dict = _model_to_dict(neg) if neg else None

        compiler = PromptCompiler()
        compiled = await compiler.compile_shot_prompt(
            shot=shot_dict,
            character_cards=char_dicts,
            style=style_dict,
            negative_lib=neg_dict,
        )
        platform_prompt = await compiler.compile_for_platform(compiled, platform)

        gen = get_image_generator(provider)
        result = await gen.generate(
            platform_prompt,
            parameters={'shot_id': shot.id, 'seed': shot.seed or None},
        )

        existing = (await db.execute(
            select(ShotAsset).where(
                ShotAsset.shot_id == shot.id,
                ShotAsset.asset_type == 'image',
            )
        )).scalars().all()
        version = len(existing) + 1

        asset = ShotAsset(
            project_id=shot.project_id,
            user_id=user_id,
            shot_id=shot.id,
            asset_type='image',
            version=version,
            file_url=result.url,
            prompt_used=result.prompt_used,
            parameters=result.parameters,
            status='passed',
            naming=f'{shot.project_id[:6]}_{shot.shot_number}_v{version}',
        )
        db.add(asset)
        await db.commit()
        await db.refresh(asset)

        # 事中守护：图片生成后跑视觉一致性门控
        gate_info = {'passed': True, 'blocking': False, 'issues': []}
        try:
            guardian = get_comic_guardian()
            gate = await guardian.gate_transition(
                db, shot, 'pending_review_image', user_id,
            )
            if gate.issues:
                await _write_gate_diagnostics(db, shot.project_id, user_id, gate)
            await db.commit()
            gate_info = {
                'passed': gate.passed,
                'blocking': gate.blocking,
                'issues': [i.to_dict() for i in gate.issues],
            }
        except Exception as e:  # noqa: BLE001 - 门控失败不影响素材入库
            logger.warning('出图门控异常（降级放行）: %s', e)

        logger.info(
            '出图任务完成: shot=%s asset=%s backend=%s',
            shot_id, asset.id, result.backend,
        )
        return {
            'asset_id': asset.id,
            'url': result.url,
            'backend': result.backend,
            'gate': gate_info,
        }
