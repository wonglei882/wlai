"""引导采纳反馈 — 苏格拉底引导效果信号采集（L4 经验进化）。

本期落地信号链路（决策日志 → 用户是否采纳/解决），
V2 将据此调整引导链权重或替换低效链。

非阻塞：失败仅日志，不破坏主链路。
"""

import logging

from app.models.pm_guidance_feedback import PMGuidanceFeedback

logger = logging.getLogger(__name__)


async def record_guidance_feedback(
    db,
    decision_log_id: str,
    project_id: str = '',
    user_id: str = '',
    issue_type: str = '',
    adopted: bool = False,
    solved: bool = False,
) -> bool:
    """记录一次引导采纳/解决反馈。返回是否成功。"""
    try:
        if not decision_log_id:
            return False
        db.add(
            PMGuidanceFeedback(
                decision_log_id=decision_log_id,
                project_id=project_id or '',
                user_id=user_id or '',
                issue_type=issue_type or '',
                adopted=bool(adopted),
                solved=bool(solved),
            )
        )
        await db.commit()
        logger.info('[GuidanceFeedback] 记录成功: decision=%s adopted=%s solved=%s', decision_log_id, adopted, solved)
        return True
    except Exception as e:  # noqa: BLE001
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning('[GuidanceFeedback] 记录失败（非阻塞）: %s', e)
        return False
