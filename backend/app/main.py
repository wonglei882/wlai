"""FastAPI 应用入口（独立部署）。

组装全部 API 路由 + 启动时注册 PM 事件监听器。

启动方式：
    uvicorn app.main:app --reload
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

logger = logging.getLogger(__name__)


def _validate_production_settings():
    """生产环境配置校验，启动时执行。"""
    import warnings
    if not settings.SESSION_SECRET_KEY:
        warnings.warn(
            'SESSION_SECRET_KEY 未配置！会话签名将使用随机密钥，重启后所有会话失效。',
            RuntimeWarning, stacklevel=2,
        )
    if settings.LOCAL_AUTH_ENABLED and not settings.LOCAL_AUTH_PASSWORD:
        warnings.warn(
            'LOCAL_AUTH_ENABLED=True 但 LOCAL_AUTH_PASSWORD 为空，本地登录无密码保护！',
            RuntimeWarning, stacklevel=2,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时注册 PM 事件监听器。"""
    _validate_production_settings()
    try:
        from app.services.core.event_bus_listeners import init_pm_event_listeners

        init_pm_event_listeners()
    except Exception as e:  # noqa: BLE001 - 监听器注册失败不应阻断启动
        logger.warning('PM 事件监听器注册失败: %s', e)
    logger.info('WLAI PM 后端服务已启动')
    yield
    logger.info('WLAI PM 后端服务已停止')


def create_app() -> FastAPI:
    app = FastAPI(
        title='WLAI PM - AI 项目经理后端服务',
        description='长篇网文创作的 PM 子系统：主动巡检、章节质量诊断、灵感与守护。',
        version='1.0.0',
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    from app.api.companion import router as companion_router
    from app.api.pm import router as pm_router
    from app.api.pm_control import router as pm_control_router
    from app.api.pm_diagnostic_logs import router as pm_diagnostic_logs_router
    from app.api.pm_token_usage import router as pm_token_usage_router

    app.include_router(pm_router)
    app.include_router(pm_control_router)
    app.include_router(pm_diagnostic_logs_router)
    app.include_router(pm_token_usage_router)
    app.include_router(companion_router)

    @app.get('/health', tags=['system'])
    async def health():
        """健康检查。"""
        return {'status': 'ok', 'service': 'wlai-pm'}

    return app


app = create_app()
