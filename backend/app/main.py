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
    logger.info('WLai PM 后端服务已启动')
    yield
    logger.info('WLai PM 后端服务已停止')


def create_app() -> FastAPI:
    app = FastAPI(
        title='ConsistencyAgent - AI 内容一致性 Agent',
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

    from app.api.companion import router as companion_router
    from app.api.pm import router as pm_router
    from app.api.pm_control import router as pm_control_router
    from app.api.pm_diagnostic_logs import router as pm_diagnostic_logs_router
    from app.api.pm_token_usage import router as pm_token_usage_router

    # API v1 — 通用一致性 Agent 接口
    from app.api.v1.content import router as v1_content_router
    from app.api.v1.reports import router as v1_reports_router
    from app.api.v1.webhooks import router as v1_webhooks_router

    # API v1 — 漫剧制片 Agent 接口
    from app.api.v1.comic_bible import router as v1_comic_bible_router
    from app.api.v1.comic_storyboard import router as v1_comic_storyboard_router

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

    @app.get('/health', tags=['system'])
    async def health():
        """健康检查。"""
        return {'status': 'ok', 'service': 'consistency-agent', 'version': '2.0.0'}

    return app


app = create_app()
