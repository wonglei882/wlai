"""WLai 漫剧端到端 Demo — 离线跑通全流水线（Mock 生成器）。

用法（在 backend 目录）:
    python ../scripts/demo_comic_pipeline.py

流程:
    项目 -> 设定圣经 -> 角色卡 -> 画风卡 -> 负面词库 -> 集数
    -> 分镜生成(规则版, 含事前守护注入) -> 逐镜头出图(Mock) -> 事中门控
所有产物写入本地数据库，图片占位 SVG 落在 backend/data/generated/。
"""

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('demo')


async def main() -> int:
    from sqlalchemy import select

    from app.database import _get_or_create_session_maker, get_engine
    from app.models.comic_bible import (
        ArtStyleCard, CharacterCard, ComicEpisode,
        NegativePromptLibrary, SettingBible,
    )
    from app.models.comic_shot import Shot, ShotAsset, Storyboard
    from app.models.project import Project
    from app.services.comic.consistency_guardian import get_comic_guardian
    from app.services.comic.prompt_compiler import PromptCompiler
    from app.services.comic.storyboard_gen import StoryboardGenerator
    from app.services.generators import get_image_generator

    engine = await get_engine()
    SessionLocal = _get_or_create_session_maker(engine)

    async with SessionLocal() as db:
        user_id = 'demo-user'

        # 1. 项目
        project = Project(
            user_id=user_id,
            title='WLai 漫剧 Demo：星空下的约定',
            description='端到端演示项目（Mock 出图）',
            genre='comic',
            status='planning',
            wizard_status='completed',
        )
        db.add(project)
        await db.flush()

        # 2. 设定圣经
        bible = SettingBible(
            project_id=project.id, user_id=user_id,
            world_name='星临城',
            world_rules='低魔世界，灵力来自星辰碎片',
        )
        db.add(bible)
        await db.flush()

        # 3. 角色卡（固定外貌提示词）
        chars = [
            CharacterCard(
                project_id=project.id, bible_id=bible.id, user_id=user_id,
                name='林星遥', gender='女', age='17',
                hair='黑色长发', eyes='红瞳', outfit='白色校服外套',
                personality='内敛坚定', voice_timbre='清冷',
                appearance_prompt='黑长直红瞳少女，白色校服，发尾微卷',
                negative_traits=['白发', '异瞳', '暴露服装'],
                status='approved',
            ),
            CharacterCard(
                project_id=project.id, bible_id=bible.id, user_id=user_id,
                name='陆离', gender='男', age='18',
                hair='银灰色短发', eyes='蓝瞳', outfit='深色风衣',
                personality='外冷内热', voice_timbre='低沉',
                appearance_prompt='银灰短发蓝瞳少年，深色风衣',
                negative_traits=['长发', '西装', '红瞳'],
                status='approved',
            ),
        ]
        db.add_all(chars)
        await db.flush()

        # 4. 画风卡
        style = ArtStyleCard(
            project_id=project.id, user_id=user_id,
            style_name='日系赛璐璐',
            base_prompt='anime style, cel shading, clean lineart, vibrant colors',
        )
        db.add(style)
        await db.flush()

        # 5. 负面词库
        db.add(NegativePromptLibrary(
            project_id=project.id, user_id=user_id,
            category='universal', prompts=['blurry', 'low quality', 'extra fingers', 'watermark'],
        ))
        await db.flush()

        # 6. 集数
        episode = ComicEpisode(
            project_id=project.id, user_id=user_id,
            episode_number=1, summary='两人在天文台发现星辰碎片',
        )
        db.add(episode)
        await db.flush()

        # 7. 事前守护：注入设定圣经上下文
        guardian = get_comic_guardian()
        bible_context = await guardian.build_script_context(db, project.id, episode.id)
        logger.info('事前守护注入上下文 %d 字', len(bible_context or ''))

        # 8. 分镜生成（规则版）
        scene_text = (
            '林星遥推开天文台的门，红瞳在月光下微微发亮。'
            '陆离站在望远镜旁抬头。'
            '他转身看向她。'
            '两人并肩望向窗外，夜空中的星辰碎片缓缓坠落。'
            '城市的灯火在远方闪烁。'
        )
        gen = StoryboardGenerator()
        result = await gen.generate_from_text(
            text=scene_text,
            project_id=project.id,
            user_id=user_id,
            episode_id=episode.id,
            character_names=['林星遥', '陆离'],
            mode='rules',
            bible_context=bible_context,
        )
        sb_data, shots_data = result['storyboard'], result['shots']
        storyboard = Storyboard(
            id=sb_data['id'], project_id=project.id,
            episode_id=episode.id, user_id=user_id,
            title=sb_data.get('title') or '第一集分镜',
            source_text=scene_text,
            shot_count=len(shots_data), status='confirmed',
        )
        db.add(storyboard)
        await db.flush()

        # 9. 创建镜头 + 出图（Mock）+ 事中门控
        compiler = PromptCompiler()
        image_gen = get_image_generator('mock')
        summary = []
        for idx, s in enumerate(shots_data, start=1):
            shot = Shot(
                id=s.get('id'), project_id=project.id,
                storyboard_id=storyboard.id, episode_id=episode.id,
                user_id=user_id,
                shot_number=s.get('shot_number') or idx,
                duration=s.get('duration', 4.0),
                scene_type=s.get('scene_type', ''),
                visual_description=s.get('visual_description', ''),
                character_action=s.get('character_action', ''),
                dialogue=s.get('dialogue', ''),
                camera_movement=s.get('camera_movement', ''),
                status='pending_script',
                metadata_json=s.get('metadata_json') or {'matched_characters': ['林星遥', '陆离']},
            )
            db.add(shot)
            await db.flush()

            shot_dict = {c.name: getattr(shot, c.name) for c in Shot.__table__.columns}
            compiled = await compiler.compile_shot_prompt(
                shot=shot_dict,
                character_cards=[
                    {'appearance_prompt': c.appearance_prompt, 'name': c.name}
                    for c in chars
                ],
                style={'base_prompt': style.base_prompt, 'style_name': style.style_name},
                negative_lib={'prompts': ['blurry']},
            )
            platform_prompt = await compiler.compile_for_platform(compiled, 'midjourney')
            shot.compiled_prompt = platform_prompt

            # Mock 出图
            r = await image_gen.generate(
                platform_prompt,
                parameters={'shot_id': shot.id, 'seed': idx * 1000},
            )
            asset = ShotAsset(
                project_id=project.id, user_id=user_id, shot_id=shot.id,
                asset_type='image', version=1, file_url=r.url,
                prompt_used=r.prompt_used, parameters=r.parameters,
                status='passed',
                naming=f'{project.id[:6]}_{shot.shot_number}_v1',
            )
            db.add(asset)

            # 事中门控（出图后视觉一致性）
            gate = await guardian.gate_transition(
                db, shot, 'pending_review_image', user_id,
            )
            score = getattr(shot, 'last_consistency_score', None)
            summary.append({
                'shot': shot.shot_number,
                'status': shot.status,
                'score': score,
                'gate_blocked': bool(gate.blocking),
                'asset': r.url,
            })

        await db.commit()

        # 10. 汇总
        print()
        print('=' * 72)
        print('WLai 漫剧 Demo 完成')
        print('=' * 72)
        print(f'项目: {project.title}  ({project.id})')
        print(f'角色卡: {len(chars)}  |  分镜: {len(shots_data)} 镜')
        print()
        for row in summary:
            score_txt = f'{row["score"]:.2f}' if row['score'] is not None else '  - '
            flag = ' [门控拦截]' if row['gate_blocked'] else ''
            print(f'  镜#{row["shot"]:>2}  状态={row["status"]:<20} 一致分={score_txt}  素材={row["asset"][-28:]}{flag}')
        print()
        print(f'占位素材目录: backend/data/generated/')
        print('浏览器访问前端后，进入该项目可查看分镜/镜头/素材。')
        return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
