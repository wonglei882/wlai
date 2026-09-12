"""PM Token 预算闸门 — 记账 + 水位告警 + 软降级（非截断）

设计契约：
- 预算耗尽 ≠ 功能截断：仅跳过本轮 LLM 增强（call_llm_with_guard 返回 None，
  调用方走已有规则兜底路径），PM 巡检循环本身照常运行。
- 问题具有持久性（角色跳变不会自愈），下一轮巡检自然重新发现并补做 LLM 增强。
- enforce_mode='observe'：只记账告警，永不拦截。
- 记账尽力而为：任何记账异常只打日志，绝不影响主流程。
"""

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

import logging
from app.models.pm_token_usage import PMTokenUsage

logger = logging.getLogger(__name__)

# 当日用量进程内缓存 user_id -> (monotonic_ts, used_tokens)
_USAGE_CACHE_TTL_SECONDS = 60
_usage_cache: dict[str, tuple[float, int]] = {}


def _budget_cfg() -> dict:
    """预算配置（独立函数便于测试 monkeypatch）。"""
    from app.services.pm.feature_config import pm_feature_config

    raw = pm_feature_config.get_cost_control()
    return {
        'max_tokens_per_day': int(raw.get('max_tokens_per_day', 100000)),
        'alert_threshold': float(raw.get('alert_threshold', 0.8)),
        'enforce_mode': str(raw.get('enforce_mode', 'degrade')),
    }


@dataclass
class BudgetContext:
    """预算上下文：随 call_llm_with_guard 传递，用于查余额与记账。

    db 由调用方注入（巡检链路中即当前 AsyncSession），记账与业务同事务提交。
    """

    user_id: str
    project_id: str = ''
    feature: str = 'inspection'
    action: str = ''
    db: Any = None
    # 预算耗尽标志：check_budget 在 degrade 模式下拒绝时置位，
    # 供调用侧（如 _decompose_repair_priority）在写日志 reason 时带 'budget_degraded' 标记。
    exhausted: bool = False


def reset_budget_cache():
    """清空当日用量缓存（测试与配置变更时使用）。"""
    _usage_cache.clear()


async def _today_used_tokens(db, user_id: str) -> int:
    """当日（本地零点起）该用户 PM LLM 总消耗 token，带 60s 进程内缓存。"""
    now = time.monotonic()
    cached = _usage_cache.get(user_id)
    if cached is not None and (now - cached[0]) < _USAGE_CACHE_TTL_SECONDS:
        return cached[1]
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(PMTokenUsage.total_tokens), 0)).where(
            PMTokenUsage.user_id == user_id,
            PMTokenUsage.created_at >= midnight,
        )
    )
    used = int(result.scalar_one() or 0)
    _usage_cache[user_id] = (now, used)
    return used


async def check_budget(db, ctx: BudgetContext) -> bool:
    """检查该用户今日 token 预算是否允许发起一次 LLM 调用。

    返回 False 仅表示"本轮跳过 LLM 增强"→ guard 返回 None → 规则兜底，
    绝不抛异常、绝不中断巡检循环。
    """
    cfg = _budget_cfg()
    limit = cfg['max_tokens_per_day']
    mode = cfg['enforce_mode']
    used = await _today_used_tokens(db, ctx.user_id)

    if used >= limit:
        if mode == 'observe':
            logger.warning(
                '[PM-Budget] 用户 %s 今日用量 %s/%s 已超限（observe 模式只告警不拦截）',
                ctx.user_id,
                used,
                limit,
            )
            return True
        logger.warning(
            '[PM-Budget] 用户 %s 今日 token 用量 %s/%s 已达上限，本轮 LLM 增强让位规则路径（下轮巡检自动恢复，非截断）',
            ctx.user_id,
            used,
            limit,
        )
        # 置位耗尽标志，供调用侧留痕（decision_reason 带 budget_degraded 标记）
        ctx.exhausted = True
        return False

    alert_ratio = cfg['alert_threshold']
    if limit > 0 and used >= int(limit * alert_ratio):
        logger.warning(
            '[PM-Budget] 用户 %s 今日用量 %s/%s 达到 %.0f%% 告警水位',
            ctx.user_id,
            used,
            limit,
            alert_ratio * 100,
        )
    return True


def _estimate_tokens(prompt_text: str = '', max_tokens_hint: int | None = None) -> tuple[int, int]:
    """无 usage 数据时的粗估：prompt 字符数 //2 + 输出上限提示值（默认 500）。"""
    prompt_est = len(prompt_text or '') // 2
    completion_est = max_tokens_hint if max_tokens_hint and max_tokens_hint > 0 else 500
    return prompt_est, completion_est


async def record_usage(
    db,
    ctx: BudgetContext,
    response: Any = None,
    *,
    model: str = '',
    provider: str = '',
    prompt_text: str = '',
    max_tokens_hint: int | None = None,
) -> None:
    """记录一次 PM LLM 调用的 token 消耗到 pm_token_usage（随业务事务提交）。

    response 为 generate_text 返回的 dict（含 usage）；缺失时按 prompt 粗估。
    """
    try:
        usage = {}
        if isinstance(response, dict):
            usage = response.get('usage') or {}
        p = int(usage.get('prompt_tokens') or 0)
        c = int(usage.get('completion_tokens') or 0)
        t = int(usage.get('total_tokens') or 0)
        if t <= 0:
            p, c = _estimate_tokens(prompt_text, max_tokens_hint)
            t = p + c
        db.add(
            PMTokenUsage(
                id=str(uuid.uuid4()),
                project_id=ctx.project_id,
                user_id=ctx.user_id,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                feature=ctx.feature,
                action=ctx.action,
                model=model,
                provider=provider,
            )
        )
        # 本次调用已产生新消耗，失效缓存保证下次检查读到最新值
        _usage_cache.pop(ctx.user_id, None)
    except Exception as e:
        logger.debug('[PM-Budget] 记账失败（不影响主流程）: %s', e)


async def get_budget_status(db, user_id: str) -> dict:
    """供 /api/pm/token-usage 展示的当日预算状态。"""
    cfg = _budget_cfg()
    used = await _today_used_tokens(db, user_id)
    limit = cfg['max_tokens_per_day']
    return {
        'used_today': used,
        'limit_today': limit,
        'remaining_ratio': max(0.0, 1.0 - (used / limit)) if limit > 0 else 1.0,
        'enforce_mode': cfg['enforce_mode'],
        'degraded': used >= limit and cfg['enforce_mode'] != 'observe',
    }
