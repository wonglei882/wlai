"""tests/api 集成测试基座 — 真实 ASGI app + sqlite 内存库 + 依赖覆盖。

策略（与既有单元测试互补，专项覆盖 T7「API 集成链路」）：
- 直接使用 app.main 模块级 app（create_app() 单例），httpx ASGITransport 打真实路由与中间件。
- 不触发 lifespan（ASGITransport 不执行 lifespan 事件）→ 避开 FERNET_KEY/生产配置校验。
- 通过 app.dependency_overrides 覆盖三个认证/会话依赖：
    app.api.v1.deps.get_db_session_depends → sqlite 内存 session
    app.api.v1.deps.get_current_user_id   → 固定测试用户
    app.database.get_db                    → sqlite 内存 session（pm 路由用）
  从而绕过 JWT 中间件的 401（中间件无 token 时仅置 state.user_id=None，被覆盖依赖）与真实数据库。
- 提供 TEST_USER_ID / OTHER_USER_ID 与 seed_project 辅助，用于直插项目数据。
  （注：代码库无项目 CRUD API 路由，T7 以 DB 直插 + 归属/绑定链路覆盖项目维度，见 task7-report。）
"""

import uuid

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# 固定测试用户（依赖覆盖后返回，替代 JWT 解析）
TEST_USER_ID = 'u_test_api_user'
OTHER_USER_ID = 'u_test_api_other'


@pytest_asyncio.fixture
async def api_env():
    """创建 sqlite 内存库、注册依赖覆盖，yield (client, Session 工厂)。

    每个测试独立建库/销毁，互不干扰。覆盖函数与原依赖同形：
    - get_db / get_db_session_depends：async generator（yield session）
    - get_current_user_id：普通 async 函数返回 str
    """
    from app.api.v1.deps import get_current_user_id, get_db_session_depends
    from app.database import get_db
    from app.main import app

    engine = create_async_engine(
        'sqlite+aiosqlite://',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )

    # 导入全部模型，注册到 Base.metadata（create_all 需要）
    from app.models.base import Base

    __import__('app.models')

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with Session() as s:
            yield s

    async def _override_get_db_session():
        async with Session() as s:
            yield s

    async def _override_get_current_user_id():
        return TEST_USER_ID

    app.dependency_overrides[get_db_session_depends] = _override_get_db_session
    app.dependency_overrides[get_current_user_id] = _override_get_current_user_id
    app.dependency_overrides[get_db] = _override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        yield client, Session

    # teardown：清理覆盖，避免污染其他测试
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(api_env):
    """仅暴露 httpx client（不需要造数时用）。"""
    client, _ = api_env
    yield client


@pytest_asyncio.fixture
async def seed_project(api_env):
    """直插 Project 的工厂 fixture（项目无 CRUD API，测试以 DB 造数）。

    用法: project_id = await seed_project(user_id='xxx', title='yyy')
    """
    async def _seed(user_id: str = TEST_USER_ID, title: str = '测试项目') -> str:
        from app.models.project import Project

        _, Session = api_env
        async with Session() as s:
            project = Project(
                id=str(uuid.uuid4()),
                user_id=user_id,
                title=title,
                description='集成测试种子项目',
                status='planning',
            )
            s.add(project)
            await s.commit()
            return project.id

    return _seed