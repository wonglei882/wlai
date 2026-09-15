"""FastAPI 应用入口（独立部署）。

组装全部 API 路由 + 启动时注册 PM 事件监听器。

启动方式：
    uvicorn app.main:app --reload
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_session_secret, settings

logger = logging.getLogger(__name__)


def _decode_jwt(token: str) -> str | None:
    """验证 JWT 并返回 user_id；失败返回 None。"""
    try:
        from jose import JWTError, jwt
    except ImportError:
        return None
    secret = get_session_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=['HS256'])
        return payload.get('sub')
    except JWTError:
        return None


def _validate_production_settings():
    """生产环境配置校验，启动时执行。"""
    import warnings
    try:
        get_session_secret()
    except RuntimeError as e:
        raise RuntimeError(f'生产环境配置校验失败: {e}') from e
    if not settings.FERNET_KEY:
        logger.critical(
            '⚠️ 安全警告：未配置 FERNET_KEY！settings 表的 api_key / cover_api_key / '
            'smtp_password 无法加解密（读写这些字段会抛错）。'
            '生成方式: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"，然后写入 .env 的 FERNET_KEY。'
        )
    if settings.LOCAL_AUTH_ENABLED and not settings.LOCAL_AUTH_PASSWORD:
        warnings.warn(
            'LOCAL_AUTH_ENABLED=True 但 LOCAL_AUTH_PASSWORD 为空，本地登录无密码保护！',
            RuntimeWarning, stacklevel=2,
        )
    # 检测默认弱密码
    _WEAK_PASSWORDS = {'admin123', 'password', '123456', 'admin'}
    if settings.LOCAL_AUTH_ENABLED and settings.LOCAL_AUTH_PASSWORD in _WEAK_PASSWORDS:
        logger.error(
            '⚠️ 安全警告：LOCAL_AUTH_PASSWORD 使用了弱密码 "%s"！'
            '生产环境请务必更换为强密码。',
            settings.LOCAL_AUTH_PASSWORD,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时注册 PM 事件监听器 + 自动创建本地管理员。"""
    _validate_production_settings()
    try:
        from app.services.core.event_bus_listeners import init_pm_event_listeners

        init_pm_event_listeners()
    except Exception as e:  # noqa: BLE001 - 监听器注册失败不应阻断启动
        logger.warning('PM 事件监听器注册失败: %s', e)

    # 自动创建本地管理员账户
    await _ensure_local_admin()

    logger.info('WLai PM 后端服务已启动')
    yield
    logger.info('WLai PM 后端服务已停止')


async def _ensure_local_admin():
    """启动时检查并创建本地管理员账户（如果不存在）。"""
    if not settings.LOCAL_AUTH_ENABLED:
        return
    username = settings.LOCAL_AUTH_USERNAME
    password = settings.LOCAL_AUTH_PASSWORD
    if not username or not password:
        return
    try:
        from passlib.context import CryptContext
        from sqlalchemy import select

        from app.database import _get_or_create_session_maker, get_engine
        from app.models.user import User

        engine = await get_engine()
        SessionLocal = _get_or_create_session_maker(engine)
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.username == username))
            if result.scalar_one_or_none():
                return  # 已存在，跳过
            user = User(
                username=username,
                password_hash=CryptContext(schemes=['bcrypt'], deprecated='auto').hash(password),
                display_name=settings.LOCAL_AUTH_DISPLAY_NAME,
                role='admin',
                must_change_password=password in {'admin123', 'password', '123456', 'admin'},
            )
            session.add(user)
            await session.commit()
            logger.info('已自动创建本地管理员账户: %s', username)
    except Exception as e:
        logger.warning('自动创建本地管理员失败: %s', e)


def create_app() -> FastAPI:
    app = FastAPI(
        title='WLai - AI 内容一致性 Agent',
        description='通用 AI 内容一致性 Agent：支持长篇小说、漫剧等多模态内容的一致性巡检、诊断与修复。',
        version='2.0.0',
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    # ── 请求耗时中间件 ─────────────────────────────────────────────
    class ProcessTimeMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            start = time.perf_counter()
            response = await call_next(request)
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            response.headers['X-Process-Time'] = f'{elapsed_ms}ms'
            if elapsed_ms > settings.database_slow_query_threshold * 1000:
                logger.warning(
                    '[SlowRequest] %s %s %.0fms',
                    request.method, request.url.path, elapsed_ms,
                )
            return response

    app.add_middleware(ProcessTimeMiddleware)

    # ── JWT 认证中间件 ──────────────────────────────────────────
    class JWTAuthMiddleware(BaseHTTPMiddleware):
        """从 Authorization header 解析 JWT，设置 request.state.user_id。"""

        # 不需要认证的路径前缀
        _PUBLIC_PREFIXES = (
            '/api/auth/login',
            '/api/auth/register',
            '/api/health',
            '/metrics',
            '/docs',
            '/openapi.json',
            '/redoc',
        )

        async def dispatch(self, request: Request, call_next):
            # OPTIONS 预检请求直接放行
            if request.method == 'OPTIONS':
                request.state.user_id = None
                return await call_next(request)

            # 公开路径跳过认证
            path = request.url.path
            if any(path.startswith(p) for p in self._PUBLIC_PREFIXES):
                request.state.user_id = None
                return await call_next(request)

            # 解析 Authorization: Bearer <token>
            auth_header = request.headers.get('Authorization', '')
            user_id = None
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
                try:
                    user_id = _decode_jwt(token)
                except Exception:
                    pass  # token 无效时 user_id 保持 None，后续由路由判断

            request.state.user_id = user_id
            return await call_next(request)

    app.add_middleware(JWTAuthMiddleware)

    # ── Prometheus 指标埋点中间件（产品化 P2-2） ─────────────────────────
    from app.api.metrics import MetricsMiddleware
    app.add_middleware(MetricsMiddleware)

    # ── 认证路由 ────────────────────────────────────────────────
    from app.api.auth import router as auth_router
    app.include_router(auth_router)

    # 项目 CRUD
    from app.api.projects import router as projects_router
    app.include_router(projects_router)

    from app.api.companion import router as companion_router
    from app.api.pm import router as pm_router
    from app.api.pm_control import router as pm_control_router
    from app.api.pm_diagnostic_logs import router as pm_diagnostic_logs_router
    from app.api.pm_token_usage import router as pm_token_usage_router

    # API v1 — 漫剧制片 Agent 路由
    from app.api.v1.comic_bible import router as v1_comic_bible_router
    from app.api.v1.comic_storyboard import router as v1_comic_storyboard_router

    # API v1 — 通用一致性 Agent 接口
    from app.api.v1.content import router as v1_content_router

    # API v1 — 小说章节路由
    from app.api.v1.novel_chapters import router as v1_novel_chapters_router
    from app.api.v1.reports import router as v1_reports_router
    from app.api.v1.tasks import router as v1_tasks_router

    # API v1 — VisGuard 角色视觉一致性
    from app.api.v1.visguard import router as v1_visguard_router
    from app.api.v1.visguard_jobs import router as v1_visguard_jobs_router
    from app.api.v1.webhooks import router as v1_webhooks_router
    from app.api.v1.ws import router as v1_ws_router

    # 现有 PM 路由（向后兼容）
    app.include_router(pm_router)
    app.include_router(pm_control_router)
    app.include_router(pm_diagnostic_logs_router)
    app.include_router(pm_token_usage_router)
    app.include_router(companion_router)

    # API v1 — 通用 Agent 路由
    app.include_router(v1_content_router)
    app.include_router(v1_reports_router)
    app.include_router(v1_webhooks_router)

    # API v1 — 漫剧制片 Agent 路由
    app.include_router(v1_comic_bible_router)
    app.include_router(v1_comic_storyboard_router)
    app.include_router(v1_tasks_router)
    app.include_router(v1_ws_router)
    app.include_router(v1_novel_chapters_router)
    app.include_router(v1_visguard_router)
    app.include_router(v1_visguard_jobs_router)

    # 健康检查路由
    from app.api.health import router as health_router
    app.include_router(health_router)

    # Prometheus 指标路由（产品化 P2-2）
    from app.api.metrics import router as metrics_router
    app.include_router(metrics_router)

    # 生成素材静态目录（Mock 生成器产物）
    from app.config import DATA_DIR
    generated_dir = DATA_DIR / 'generated'
    generated_dir.mkdir(parents=True, exist_ok=True)
    app.mount('/generated', StaticFiles(directory=str(generated_dir)), name='generated')

    # ── 全局异常处理器 ──────────────────────────────────────────
    from app.core.exceptions import BusinessException

    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        return JSONResponse(
            status_code=exc.status_code,
            content={'error': exc.code, 'message': exc.message},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception('Unhandled exception: %s', exc)
        return JSONResponse(
            status_code=500,
            content={'error': 'internal_server_error', 'message': '服务内部错误，请稍后重试'},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # 4xx 与 503 返回原始 detail：503 的 detail 是客户端可读的提示文案
        # （如"生成后端未配置"），其余 5xx 隐藏内部信息，避免泄漏堆栈/路径
        detail = exc.detail if exc.status_code < 500 or exc.status_code == 503 else '服务内部错误'
        return JSONResponse(
            status_code=exc.status_code,
            content={'error': detail},
        )

    return app


app = create_app()