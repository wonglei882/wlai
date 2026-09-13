"""Webhook 管理 API — 外部系统注册回调以接收一致性事件通知。

端点:
    POST /api/v1/webhooks       — 注册 Webhook
    GET  /api/v1/webhooks       — 查询已注册 Webhook
    DELETE /api/v1/webhooks/{id} — 删除 Webhook
"""

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/webhooks', tags=['consistency-agent'])


# =============================================================================
# 请求/响应模型
# =============================================================================


class WebhookCreateRequest(BaseModel):
    """Webhook 注册请求。"""

    project_id: str
    url: str = Field(..., description='回调 URL')
    events: list[str] = Field(..., description='订阅事件列表')
    secret: str = Field(..., min_length=8, description='HMAC 签名密钥（至少 8 字符）')
    description: str = Field(default='', description='描述')


class WebhookResponse(BaseModel):
    """Webhook 响应。"""

    id: str
    project_id: str
    url: str
    events: list[str]
    is_active: bool
    last_triggered_at: str | None = None
    last_status: str | None = None
    created_at: str = ''


# =============================================================================
# 辅助函数
# =============================================================================


def _get_user_id(request: Request) -> str:
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail='未登录或用户 ID 缺失')
    return user_id


def sign_payload(secret: str, payload: dict) -> str:
    """生成 HMAC-SHA256 签名。"""
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        secret.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


async def fire_webhook(webhook, event_type: str, payload: dict) -> bool:
    """触发 Webhook 回调（带 HMAC 签名）。

    Returns:
        是否成功
    """
    import httpx

    signature = sign_payload(webhook.secret, payload)
    headers = {
        'X-CA-Event': event_type,
        'X-CA-Signature': signature,
        'X-CA-Timestamp': str(int(time.time())),
        'Content-Type': 'application/json',
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook.url, json=payload, headers=headers)
            success = 200 <= resp.status_code < 300
            webhook.last_status = 'success' if success else 'failed'
            return success
    except Exception as e:
        logger.warning('[Webhook] 回调失败 %s: %s', webhook.url[:50], e)
        webhook.last_status = 'failed'
        return False


# =============================================================================
# 端点
# =============================================================================


@router.post('', response_model=WebhookResponse)
async def create_webhook(
    body: WebhookCreateRequest,
    request: Request,
):
    """注册 Webhook 回调。"""
    from app.models.webhook import WebhookConfig
    from app.database import get_db_session

    user_id = _get_user_id(request)
    db = await get_db_session(user_id)
    try:
        webhook = WebhookConfig(
            project_id=body.project_id,
            user_id=user_id,
            url=body.url,
            events=body.events,
            secret=body.secret,
            description=body.description,
        )
        db.add(webhook)
        await db.commit()
        await db.refresh(webhook)

        logger.info('[CA] Webhook 注册成功: id=%s url=%s', webhook.id, body.url[:50])
        return WebhookResponse(
            id=webhook.id,
            project_id=webhook.project_id,
            url=webhook.url,
            events=webhook.events,
            is_active=webhook.is_active,
            created_at=str(webhook.created_at or ''),
        )
    except Exception as e:
        await db.rollback()
        logger.error('[CA] Webhook 注册失败: %s', e)
        raise HTTPException(status_code=500, detail=f'注册失败: {e}')
    finally:
        await db.close()


@router.get('', response_model=list[WebhookResponse])
async def list_webhooks(
    request: Request,
    project_id: str,
):
    """查询已注册的 Webhook 列表。"""
    from app.models.webhook import WebhookConfig
    from app.database import get_db_session

    user_id = _get_user_id(request)
    db = await get_db_session(user_id)
    try:
        result = await db.execute(
            select(WebhookConfig).where(
                WebhookConfig.project_id == project_id,
                WebhookConfig.user_id == user_id,
            )
        )
        webhooks = []
        for wh in result.scalars().all():
            webhooks.append(
                WebhookResponse(
                    id=wh.id,
                    project_id=wh.project_id,
                    url=wh.url,
                    events=wh.events,
                    is_active=wh.is_active,
                    last_triggered_at=str(wh.last_triggered_at) if wh.last_triggered_at else None,
                    last_status=wh.last_status,
                    created_at=str(wh.created_at or ''),
                )
            )
        return webhooks
    finally:
        await db.close()


@router.delete('/{webhook_id}')
async def delete_webhook(
    webhook_id: str,
    request: Request,
):
    """删除 Webhook。"""
    from app.models.webhook import WebhookConfig
    from app.database import get_db_session
    from sqlalchemy import delete

    user_id = _get_user_id(request)
    db = await get_db_session(user_id)
    try:
        result = await db.execute(
            delete(WebhookConfig).where(
                WebhookConfig.id == webhook_id,
                WebhookConfig.user_id == user_id,
            )
        )
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail='Webhook 不存在')
        return {'status': 'deleted', 'id': webhook_id}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f'删除失败: {e}')
    finally:
        await db.close()
