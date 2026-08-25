"""pytest 共享 fixture。

- sys.path 注入项目根目录（原有）
- DB 集成测试基建：sqlite+aiosqlite 内存库 + Base.metadata.create_all + 异步 session
  （database.py 的 JSONB().with_variant(JSON(),'sqlite') 保证模型在 sqlite 上可建表）
"""
import sys
from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest_asyncio.fixture
async def db_session():
    """sqlite 内存库异步 session（每测试独立，自动建表/丢弃）。

    使用 StaticPool 保持单连接，避免 sqlite :memory: 跨连接丢失数据。
    """
    engine = create_async_engine(
        'sqlite+aiosqlite://',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )

    # 导入全部模型，注册到 Base.metadata（create_all 需要）
    from app.models.base import Base

    __import__('app.models')  # 触发所有模型类注册

    # 历史遗留：characters.main_career_id 引用 careers.id，但 careers 无模型类。
    # 注册占位表以便 create_all 能解析该外键（测试不涉及 careers 数据）。
    if 'careers' not in Base.metadata.tables:
        from sqlalchemy import Column, String, Table

        Table('careers', Base.metadata, Column('id', String(36), primary_key=True))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        yield session

    await engine.dispose()
