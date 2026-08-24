"""PM LLM 调用保护 — 超时 + 熔断 + 重试退避。

防止 AI 服务不可用时 PM Agent 修复/验证链路裸奔。
- 超时：单次调用超过 30s 自动取消
- 熔断：连续失败 6 次后开路，60s 后半开探测
- 重试：超时/网络错误重试 1 次，退避 2s
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any
from collections.abc import Callable, Awaitable

from app.logger import get_logger

logger = get_logger(__name__)

# 超时（秒）
LLM_TIMEOUT_SECONDS = 30
# 重试次数
LLM_MAX_RETRIES = 1
# 重试退避（秒）
LLM_RETRY_BACKOFF_SECONDS = 2
# 熔断阈值：连续失败次数（生产实证 3 次过敏感，AI 服务偶发抖动即误熔断，放宽至 6）
CIRCUIT_BREAK_THRESHOLD = 6
# 熔断恢复时间（秒）：开路后多久尝试半开
CIRCUIT_BREAK_RECOVERY_SECONDS = 60
# P2-1 自适应升级：熔断指数退避基准（秒），实际恢复时间 = base × 2^(fail_count-1)，上限 300s
CIRCUIT_RECOVERY_BASE = 30
CIRCUIT_RECOVERY_MAX = 300

# P1: 全局降级（任意 breaker 开路 → 全局 AI 服务疑似不可用，所有 breaker 共享降级窗口）
# 解决"8 项目 × 4 handler 各自冷却，AI 服务抖动时重复撞墙"问题
_GLOBAL_DEGRADED_SECONDS = 300  # 全局降级持续 300s（生产实证 30s 过短：抖动未恢复即反复撞墙）
_global_degraded_until: float = 0.0  # 全局降级截止时间戳（模块级共享态）


class CircuitState(Enum):
    CLOSED = 'closed'  # 正常，允许调用
    OPEN = 'open'  # 熔断，拒绝调用
    HALF_OPEN = 'half_open'  # 半开，允许一次探测


def is_global_degraded() -> bool:
    """全局降级检查：任意 breaker 开路时触发，所有 LLM 调用共享降级窗口。

    用于"AI 服务抖动 → 全局熔断"，避免多项目/多 handler 重复撞墙。
    """
    return time.time() < _global_degraded_until


def _trigger_global_degraded(reason: str) -> None:
    """触发全局降级窗口。任意 breaker 进入 OPEN 时调用。"""
    global _global_degraded_until
    new_until = time.time() + _GLOBAL_DEGRADED_SECONDS
    # 仅当窗口被显著延长时记录日志（避免每次失败都刷屏）
    if new_until > _global_degraded_until + 5:
        _global_degraded_until = new_until
        logger.warning(f'[LLM-Guard] 全局降级窗口触发: {reason}（持续 {_GLOBAL_DEGRADED_SECONDS}s，所有 LLM 调用将 fast-fail）')
    else:
        _global_degraded_until = new_until


@dataclass
class CircuitBreaker:
    """自适应熔断器：指数退避恢复 + 成功后退化阈值。

    - 失败：恢复时间 = CIRCUIT_RECOVERY_BASE × 2^(fail_count-1)，上限 CIRCUIT_RECOVERY_MAX
    - 半开成功：fail_count -= 1（阈值逐步退化），避免一次抖动后长时间敏感
    - 全局降级窗口也用指数退避（基础 30s，网络抖动时逐步拉长）
    """

    name: str
    _fail_count: int = 0
    _state: CircuitState = CircuitState.CLOSED
    _opened_at: float = 0.0
    _half_open_successes: int = 0  # 半开成功计数，用于阈值退化

    def _recovery_seconds(self) -> int:
        """指数退避恢复时间：fail_count 越大恢复越慢，上限 300s。"""
        return min(CIRCUIT_RECOVERY_MAX, CIRCUIT_RECOVERY_BASE * (2 ** (self._fail_count - 1)))

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and time.time() - self._opened_at >= self._recovery_seconds():
            self._state = CircuitState.HALF_OPEN
            logger.info(f'[LLM-Guard] 熔断器 {self.name} 进入半开状态（恢复时间 {self._recovery_seconds()}s）')
        return self._state

    def record_success(self):
        if self._state == CircuitState.HALF_OPEN:
            # 半开探测成功：退化 fail_count，下次开路阈值升高
            self._fail_count = max(0, self._fail_count - 1)
            self._half_open_successes += 1
            logger.info(f'[LLM-Guard] 熔断器 {self.name} 半开探测成功，fail_count 退化至 {self._fail_count}（已成功 {self._half_open_successes} 次）')
        self._state = CircuitState.CLOSED

    def record_failure(self):
        self._fail_count += 1
        effective_threshold = max(1, CIRCUIT_BREAK_THRESHOLD - self._half_open_successes)
        if self._fail_count >= effective_threshold:
            if self._state != CircuitState.OPEN:
                logger.warning(f'[LLM-Guard] 熔断器 {self.name} 开路（连续失败 {self._fail_count} 次，阈值 {effective_threshold}）')
                _trigger_global_degraded(f'{self.name} 连续失败 {self._fail_count} 次')
            self._state = CircuitState.OPEN
            self._opened_at = time.time()
        elif self._state == CircuitState.HALF_OPEN:
            logger.warning(f'[LLM-Guard] 熔断器 {self.name} 半开探测失败，重新开路')
            self._state = CircuitState.OPEN
            self._opened_at = time.time()
            _trigger_global_degraded(f'{self.name} 半开探测失败')

    @property
    def fail_count(self) -> int:
        return self._fail_count


# 全局熔断器注册表（按用途隔离，动态创建的 breaker 也持久化状态）
_breaker_registry: dict[str, CircuitBreaker] = {
    'world_drift_fix': CircuitBreaker(name='world_drift_fix'),
    'quality_score_verify': CircuitBreaker(name='quality_score_verify'),
}


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """获取指定用途的熔断器实例。动态创建的 breaker 也会注册到全局表，状态持久。"""
    if name not in _breaker_registry:
        _breaker_registry[name] = CircuitBreaker(name=name)
    return _breaker_registry[name]


def get_all_circuit_breakers() -> dict[str, CircuitBreaker]:
    """返回所有已注册的熔断器实例（供监控/健康检查使用）。"""
    return dict(_breaker_registry)


async def call_llm_with_guard(
    llm_func: Callable[..., Awaitable[Any]],
    *,
    breaker_name: str,
    prompt: str = '',
    budget_ctx: Any | None = None,
    **kwargs: Any,
) -> Any | None:
    """带超时 + 熔断 + 重试的 LLM 调用包装。

    Args:
        llm_func: 异步 LLM 调用函数（如 ai.generate_text）
        breaker_name: 熔断器名称
        prompt: prompt 内容（仅用于日志截断）
        budget_ctx: 可选 BudgetContext — token 预算软降级。
            预算耗尽时返回 None（调用方走已有规则兜底路径，非截断），
            调用成功后自动记账到 pm_token_usage（与业务同事务提交）。
        **kwargs: 传给 llm_func 的额外参数

    Returns:
        LLM 返回结果，或 None（熔断/超时/失败/预算耗尽）
    """
    breaker = get_circuit_breaker(breaker_name)

    # 熔断检查
    if breaker.state == CircuitState.OPEN:
        logger.warning(f'[LLM-Guard] {breaker_name} 熔断中，跳过 LLM 调用')
        return None

    # P1: 全局降级检查（任意 breaker 开路时触发，所有 LLM 调用 fast-fail）
    if is_global_degraded():
        logger.debug(f'[LLM-Guard] {breaker_name} 全局降级中，跳过 LLM 调用')
        return None

    # P-Budget: token 预算软降级检查（不抛异常；db 未注入时跳过检查）
    _has_db = budget_ctx is not None and getattr(budget_ctx, 'db', None) is not None
    if _has_db:
        try:
            from app.services.pm.pm_token_budget import check_budget

            if not await check_budget(budget_ctx.db, budget_ctx):
                return None
        except Exception as e:
            logger.debug(f'[LLM-Guard] {breaker_name} 预算检查异常（放行）: {e}')

    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            result = await asyncio.wait_for(
                llm_func(prompt=prompt, **kwargs) if prompt else llm_func(**kwargs),
                timeout=LLM_TIMEOUT_SECONDS,
            )
            breaker.record_success()

            # P-Budget: 成功后记账（尽力而为，随业务事务提交）
            if _has_db:
                try:
                    from app.services.pm.pm_token_budget import record_usage

                    await record_usage(
                        budget_ctx.db,
                        budget_ctx,
                        result,
                        model=str(kwargs.get('model') or ''),
                        provider=str(kwargs.get('provider') or ''),
                        prompt_text=prompt,
                        max_tokens_hint=kwargs.get('max_tokens'),
                    )
                except Exception as e:
                    logger.debug(f'[LLM-Guard] {breaker_name} 记账失败（不影响主流程）: {e}')

            logger.debug(f'[LLM-Guard] {breaker_name} 调用成功 (attempt={attempt + 1})')
            return result

        except TimeoutError:
            logger.warning(f'[LLM-Guard] {breaker_name} 超时 (>{LLM_TIMEOUT_SECONDS}s, attempt={attempt + 1}/{LLM_MAX_RETRIES + 1})')
            if attempt < LLM_MAX_RETRIES:
                await asyncio.sleep(LLM_RETRY_BACKOFF_SECONDS)
                continue

        except Exception as e:
            logger.warning(f'[LLM-Guard] {breaker_name} 调用失败 (attempt={attempt + 1}/{LLM_MAX_RETRIES + 1}): {e}')
            if attempt < LLM_MAX_RETRIES:
                await asyncio.sleep(LLM_RETRY_BACKOFF_SECONDS)
                continue

    breaker.record_failure()
    return None


def get_circuit_status() -> dict[str, Any]:
    """获取所有熔断器状态（供 /pm-control/status 健康检查使用）。"""
    _wd_breaker = _breaker_registry['world_drift_fix']
    _qs_breaker = _breaker_registry['quality_score_verify']
    return {
        'world_drift_fix': {
            'state': _wd_breaker.state.value,
            'fail_count': _wd_breaker.fail_count,
        },
        'quality_score_verify': {
            'state': _qs_breaker.state.value,
            'fail_count': _qs_breaker.fail_count,
        },
        # P1: 全局降级状态（AI 服务疑似不可用时所有 breaker 共享降级窗口）
        'global_degraded': {
            'degraded': is_global_degraded(),
            'remaining_seconds': max(0.0, _global_degraded_until - time.time()) if is_global_degraded() else 0.0,
        },
    }
