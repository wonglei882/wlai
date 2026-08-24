"""
陪伴 API — 四维智能创作陪伴端点（苏格拉底 / 家教 / 百科 / 秘书）

提供：
- GET  /api/companion/socratic/{project_id}       — 生成苏格拉底引导问题链
- POST /api/companion/socratic/{project_id}/reply — 提交回答，获得引导反馈
- GET  /api/companion/knowledge                   — 按主题检索创作百科
- GET  /api/companion/briefing/{project_id}       — 生成每日贴心简报

挂载：由上层 main.py 统一注册（本副本不含 main，保持模块可导入）。
companion 为可选功能：feature 开关关闭时各端点返回明确提示而非报错。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_db
from app.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix='/companion', tags=['Companion'])


async def _companion_enabled() -> bool:
    """读取 companion 功能开关。"""
    try:
        from app.services.pm.feature_config import is_pm_feature_enabled

        return is_pm_feature_enabled('optional.companion')
    except Exception as e:  # noqa: BLE001
        logger.warning('[companion API] 功能开关读取失败: %s', e)
        return False


async def _get_profile(db, user_id: str):
    from app.models.pm_user_profile import PMUserProfile

    r = await db.execute(select(PMUserProfile).where(PMUserProfile.user_id == user_id).limit(1))
    return r.scalar_one_or_none()


async def _validate_project_ownership(db, project_id: str, user_id: str) -> None:
    from app.models.project import Project

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail='项目不存在')
    if project.user_id != user_id:
        raise HTTPException(status_code=403, detail='无权访问此项目数据')


# =============================================================================
# 请求模型
# =============================================================================
class SocraticIssueIn(BaseModel):
    """引导输入：待引导的创作问题。"""
    type: str = 'pacing'                      # 问题类型（对应引导白名单）
    message: str = ''                         # 问题描述


class SocraticReplyIn(BaseModel):
    """用户对某一引导问题的回答。"""
    issue_type: str = 'pacing'
    message: str = ''
    answer: str


# =============================================================================
# S · 苏格拉底引导
# =============================================================================
@router.get('/socratic/{project_id}')
async def get_socratic_questions(
    project_id: str,
    user_id: str,
    issue_type: str = 'pacing',
    message: str = '',
    db=Depends(get_db),
):
    """生成苏格拉底三级引导问题链（不直接给答案）。"""
    if not await _companion_enabled():
        return {'enabled': False, 'message': '陪伴功能未开启（pm_features: optional.companion）'}
    await _validate_project_ownership(db, project_id, user_id)

    from app.services.companion import build_socratic_chain

    chain = build_socratic_chain({'type': issue_type, 'message': message})
    return {'enabled': True, 'project_id': project_id, 'mode': 'socratic', **chain}


@router.post('/socratic/{project_id}/reply')
async def submit_socratic_reply(
    project_id: str,
    user_id: str,
    payload: SocraticReplyIn,
    db=Depends(get_db),
):
    """提交对引导问题的回答，获得原则性反馈（仍不直接给答案）。"""
    if not await _companion_enabled():
        return {'enabled': False, 'message': '陪伴功能未开启（pm_features: optional.companion）'}
    await _validate_project_ownership(db, project_id, user_id)

    from app.services.companion import generate_socratic_reply

    reply = await generate_socratic_reply(
        db, user_id, {'type': payload.issue_type, 'message': payload.message}, payload.answer,
    )
    return {'enabled': True, 'feedback': reply}


# =============================================================================
# E · 百科知识
# =============================================================================
@router.get('/knowledge')
async def get_knowledge(topic: str, top_k: int = 3, user_id: str = '', db=Depends(get_db)):
    """按主题检索创作百科（种子百科 + 用户经验技能库）。"""
    from app.services.companion import get_knowledge_context, search_knowledge

    hits = search_knowledge(topic, top_k=top_k)
    context = await get_knowledge_context(user_id, topic, db) if user_id else ''
    return {
        'topic': topic,
        'knowledge_hits': hits,
        'context': context,
    }


# =============================================================================
# P · 秘书简报
# =============================================================================
@router.get('/briefing/{project_id}')
async def get_daily_briefing(project_id: str, user_id: str, db=Depends(get_db)):
    """生成每日贴心创作简报。"""
    await _validate_project_ownership(db, project_id, user_id)

    from app.models.project import Project
    from app.services.companion import compose_daily_briefing

    r = await db.execute(select(Project).where(Project.id == project_id))
    project = r.scalar_one_or_none()
    ctx = {'title': project.title if project else '', 'chapter_count': getattr(project, 'chapter_count', None)}
    profile = await _get_profile(db, user_id)
    briefing = compose_daily_briefing(project_ctx=ctx, profile=profile)
    return {'enabled': True, **briefing}
