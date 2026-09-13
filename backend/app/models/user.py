"""用户认证模型 — 本地账户登录/注册。"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean
from app.models.base import Base


def _gen_user_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    """本地用户表（username + bcrypt 密码哈希）。"""

    __tablename__ = 'users'

    id = Column(String(36), primary_key=True, default=_gen_user_id)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    display_name = Column(String(128), default='')
    role = Column(String(32), default='user')  # user / admin
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False, comment='首登强制改密')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
