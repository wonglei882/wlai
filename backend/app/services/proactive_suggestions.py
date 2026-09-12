"""主动建议引擎 — 在恰当时机向用户推送写作建议"""

import logging

logger = logging.getLogger(__name__)


async def generate_proactive_suggestions(project_id: str, db, ai_service=None) -> list[dict]:
    """
    生成主动建议，在合适时机推送给用户。

    返回格式：
    [
        {
            "type": "foreshadow_overdue",
            "message": "有 5 个伏笔尚未回收",
            "priority": "high",
            "details": ["伏笔1", "伏笔2"]
        }
    ]
    """
    suggestions = []

    try:
        from sqlalchemy import select
        from app.models.chapter import Chapter
        from app.models.foreshadow import Foreshadow
        from app.models.character import Character
        from app.models.project import Project

        # 获取项目信息
        proj_r = await db.execute(select(Project).where(Project.id == project_id))
        project = proj_r.scalar_one_or_none()
        if not project:
            return suggestions

        # 获取所有章节
        ch_r = await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number))
        chapters = list(ch_r.scalars().all())

        # 获取所有伏笔
        f_r = await db.execute(select(Foreshadow).where(Foreshadow.project_id == project_id))
        foreshadows = list(f_r.scalars().all())

        # 获取角色
        char_r = await db.execute(select(Character).where(Character.project_id == project_id))
        chars = list(char_r.scalars().all())

        # === 检查1: 最新章节内容偏短 ===
        if chapters:
            latest = chapters[-1]
            if latest.content and len(latest.content) < 500:
                suggestions.append(
                    {
                        'type': 'content_short',
                        'message': f'第 {latest.chapter_number} 章内容较短（{len(latest.content)}字），是否需要补充情节细节？',
                        'priority': 'medium',
                        'details': [],
                    }
                )

        # === 检查2: 伏笔未回收过多 ===
        if foreshadows:
            unresolved = [f for f in foreshadows if getattr(f, 'status', '') == 'planted']
            if len(unresolved) > 5:
                suggestions.append(
                    {
                        'type': 'foreshadow_overdue',
                        'message': f'有 {len(unresolved)} 个伏笔尚未回收，建议在后续章节中安排回收',
                        'priority': 'high',
                        'details': [getattr(f, 'description', '')[:60] for f in unresolved[:3]],
                    }
                )

        # === 检查3: 主角长时间未出场 ===
        main_chars = [c for c in chars if getattr(c, 'role_type', '') == 'protagonist']
        if main_chars and chapters:
            for mc in main_chars[:2]:
                # 简单检测：在最近2章中搜索主角名
                recent_content = ''
                for ch in chapters[-2:]:
                    if ch.content:
                        recent_content += ch.content
                if mc.name and mc.name not in recent_content:
                    suggestions.append(
                        {'type': 'character_missing', 'message': f'主角「{mc.name}」已超过 2 章未出场', 'priority': 'medium', 'details': []}
                    )

        # === 检查4: 连续字数下降趋势 ===
        if len(chapters) >= 3:
            word_counts = [len(ch.content or '') for ch in chapters[-3:]]
            if all(word_counts[i] > word_counts[i + 1] for i in range(2)):
                suggestions.append(
                    {
                        'type': 'word_count_declining',
                        'message': '最近 3 章字数持续下降，注意保持章节质量',
                        'priority': 'low',
                        'details': [f'第{chapters[-3 + i].chapter_number}章: {wc}字' for i, wc in enumerate(word_counts)],
                    }
                )

    except Exception as e:
        logger.warning(f'[ProactiveSuggestions] 生成建议失败: {e}')

    return suggestions
