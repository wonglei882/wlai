"""Webhook 告警通知服务 — 将一致性事件外发给已注册回调（产品化 P2-3）。

在关键业务节点调用 notify_event：
- 巡检发现问题                → issue_detected
- 巡检完成（含问题数）         → scan_finished
- 修复完成                    → fix_completed
- 成本 / Token 预算告警        → cost_threshold_exceeded

设计契约：
- 独立 Session 查询并触发回调，绝不干扰调用方事务；全程尽力而为，异常仅记日志。
- 回调复用 app.api.v1.webhooks.fire_webhook（HMAC-SHA256 签名 + X-CA-* 头）。
- 成本告警按 (user_id, 日期) 去重，每天每用户至多触发一次，避免高频巡检刷屏。
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

logger = logging.getLogger(__name__)

# 成本告警去重集合：(user_id, YYYY-MM-DD)
_cost_alert_fired: set[tuple[str, str]] = set()


def reset_cost_alert_cache() -> None:
    """清空成本告警去重缓存（测试与配置变更时使用）。"""
    _cost_alert_fired.clear()


async def notify_event(
    *,
    event_type: str,
    project_id: str,
    user_id: str,
    payload: dict,
) -> int:
    """触发订阅了指定事件的所有活跃 Webhook。

    Returns:
        成功回调的 webhook 数量（尽力而为，异常不抛出）。
    """
    if not project_id or not user_id:
        return 0
    db = None
    fired = 0
    try:
        from app.api.v1.webhooks import fire_webhook
        from app.database import get_db_session
        from app.models.webhook import WebhookConfig

        db = await get_db_session(user_id)
        result = await db.execute(
            select(WebhookConfig).where(
                WebhookConfig.project_id == project_id,
                WebhookConfig.is_active.is_(True),
            )
        )
        hooks = result.scalars().all()
        if not hooks:
            return 0

        now = datetime.now()
        for wh in hooks:
            events = wh.events or []
            if event_type not in events:
                continue
            ok = await fire_webhook(wh, event_type, payload)
            wh.last_triggered_at = now
            if ok:
                fired += 1
        await db.commit()
    except Exception as e:  # noqa: BLE001 - 通知失败不影响主流程
        logger.warning('[WebhookAlert] %s 通知失败: %s', event_type, e)
    finally:
        if db is not None:
            try:
                await db.close()
            except Exception:  # noqa: BLE001
                pass
    return fired


async def notify_cost_threshold(
    user_id: str,
    project_id: str,
    used: int,
    limit: int,
    alert_ratio: float,
) -> None:
    """成本 / Token 预算告警（按用户每日去重）。"""
    day = datetime.now().strftime('%Y-%m-%d')
    key = (user_id, day)
    if key in _cost_alert_fired:
        return
    _cost_alert_fired.add(key)
    await notify_event(
        event_type='cost_threshold_exceeded',
        project_id=project_id,
        user_id=user_id,
        payload={
            'level': 'warning',
            'message': '当日 Token 用量达到预算告警水位',
            'used_today': used,
            'limit_today': limit,
            'alert_threshold': alert_ratio,
            'used_ratio': round(used / limit, 3) if limit > 0 else 0,
            'timestamp': datetime.now().isoformat(timespec='seconds'),
        },
    )
