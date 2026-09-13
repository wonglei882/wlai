"""认证路由 — 登录 / 注册 / 当前用户。

路由前缀: /api/auth
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/auth', tags=['auth'])


# ── 请求/响应模型 ──────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=4, max_length=128)
    display_name: str = ''


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    role: str


# ── 工具函数 ──────────────────────────────────────────────────


def _get_pwd_context():
    """懒加载 passlib CryptContext（避免模块级导入开销）。"""
    from passlib.context import CryptContext
    return CryptContext(schemes=['bcrypt'], deprecated='auto')


def _hash_password(password: str) -> str:
    return _get_pwd_context().hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
    return _get_pwd_context().verify(plain, hashed)


def _create_token(user_id: str) -> str:
    """签发 JWT access_token。"""
    from jose import jwt

    secret = settings.SESSION_SECRET_KEY or settings.app_name
    expire = datetime.utcnow() + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
    payload = {
        'sub': user_id,
        'exp': expire,
        'iat': datetime.utcnow(),
    }
    return jwt.encode(payload, secret, algorithm='HS256')


def _decode_token(token: str) -> str | None:
    """验证并解码 JWT，返回 user_id；失败返回 None。"""
    from jose import jwt, JWTError

    secret = settings.SESSION_SECRET_KEY or settings.app_name
    try:
        payload = jwt.decode(token, secret, algorithms=['HS256'])
        return payload.get('sub')
    except JWTError:
        return None


async def _get_db_session(request: Request) -> AsyncSession:
    """认证路由专用的数据库会话（不依赖 request.state.user_id）。"""
    from app.database import get_engine, _get_or_create_session_maker

    engine = await get_engine()
    SessionLocal = _get_or_create_session_maker(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        await session.close()


# ── 端点 ──────────────────────────────────────────────────────


@router.post('/login', response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(_get_db_session),
):
    """本地账户登录，返回 JWT。"""
    from app.models.user import User

    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if not user or not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail='用户名或密码错误')

    if not user.is_active:
        raise HTTPException(status_code=403, detail='账户已被禁用')

    token = _create_token(user.id)
    logger.info('用户登录成功: %s (%s)', user.username, user.id)
    return TokenResponse(access_token=token)


@router.post('/register', response_model=TokenResponse)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(_get_db_session),
):
    """注册新用户，返回 JWT。"""
    from app.models.user import User

    # 检查用户名是否已存在
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail='用户名已存在')

    # 创建用户
    user = User(
        username=body.username,
        password_hash=_hash_password(body.password),
        display_name=body.display_name or body.username,
        role='user',
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = _create_token(user.id)
    logger.info('新用户注册: %s (%s)', user.username, user.id)
    return TokenResponse(access_token=token)


@router.get('/me', response_model=UserResponse)
async def me(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取当前登录用户信息。"""
    from app.models.user import User

    # 从中间件设置的 request.state.user_id 获取
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail='未登录')

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail='用户不存在')

    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        role=user.role or 'user',
    )
