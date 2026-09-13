"""API v1 公共依赖 — 数据库会话 + 用户认证。

所有 API v1 路由统一使用 Depends(get_db) + Depends(get_current_user_id)，
不再手动管理 db.close()。
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db


async def get_current_user_id(request: Request) -> str:
    """从 request.state 提取 user_id，未登录返回 401。"""
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail='未登录或用户ID缺失')
    return user_id


async def get_db_session_depends(
    request: Request,
) -> AsyncSession:
    """FastAPI Depends 专用的数据库会话依赖。

    复用 database.get_db 生成器（含回滚/统计/泄漏检测），
    通过 request.state 传递 user_id。
    """
    # get_db 是一个 async generator（yield session），需要手动驱动
    gen = get_db(request)
    try:
        session = await gen.__anext__()
        yield session
    finally:
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
