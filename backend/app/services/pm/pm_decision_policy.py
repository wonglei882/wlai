"""PM 决策策略 — 自主等级阈值统一

修复断裂：api/pm.py 提供 PMAutonomyConfig 配置 API（advisor/advisor_plus/autonomous），
但引擎决策 (_decide_action) 从未读取该配置——硬编码 0.50/0.30 阈值。

本模块把 PMAutonomyConfig.level 映射为决策阈值，供 _decide_action 消费：
- advisor:      0.80/0.50（保守：高分才自动修）
- advisor_plus: 0.50/0.30（与历史硬编码行为完全一致 = 默认兼容值）
- autonomous:   0.35/0.20（激进：低分也自动修）

保险丝：yaml 开关 core.autonomy_unify 关闭时忽略 DB 配置，行为退回 advisor_plus。
缓存：进程内 TTL 缓存（默认 300s），避免每轮巡检重复查表。
"""

from datetime import datetime, timedelta
from typing import Any

from app.logger import get_logger
from app.services.pm.feature_config import is_pm_feature_enabled

logger = get_logger(__name__)

# 自主等级 → {auto: 直接执行阈值, suggest: suggestion 降级阈值}
LEVEL_THRESHOLDS: dict[str, dict[str, float]] = {
    'advisor': {'auto': 0.80, 'suggest': 0.50},
    'advisor_plus': {'auto': 0.50, 'suggest': 0.30},
    'autonomous': {'auto': 0.35, 'suggest': 0.20},
}

_DEFAULT_LEVEL = 'advisor_plus'
_TTL_SECONDS = 300

# 进程内缓存 {project_id: (level, expires_at)}
_level_cache: dict[str, tuple[str, datetime]] = {}


def _unify_enabled() -> bool:
    """yaml 保险丝开关（core.autonomy_unify）。关闭时不读 DB 配置。"""
    try:
        return is_pm_feature_enabled('core.autonomy_unify')
    except Exception:
        return False


def reset_policy_cache():
    """清空等级缓存（测试 / 配置变更后调用）。"""
    _level_cache.clear()


async def get_effective_level(db, project_id: str) -> str:
    """读取项目有效自主等级。

    开关关闭 / 无配置行 / 非法值 / DB 异常 → advisor_plus（与历史硬编码行为一致）。
    """
    cached = _level_cache.get(project_id)
    if cached and cached[1] > datetime.now():
        return cached[0]

    level = _DEFAULT_LEVEL
    if _unify_enabled():
        try:
            from sqlalchemy import select

            from app.models.pm_autonomy_config import PMAutonomyConfig

            result = await db.execute(select(PMAutonomyConfig).where(PMAutonomyConfig.project_id == project_id).limit(1))
            row = result.scalar_one_or_none()
            if row and row.level in LEVEL_THRESHOLDS:
                level = row.level
        except Exception as e:
            logger.debug(f'[PM-Policy] 读取自主等级失败，使用默认 {_DEFAULT_LEVEL}: {e}')

    _level_cache[project_id] = (level, datetime.now() + timedelta(seconds=_TTL_SECONDS))
    return level


def get_thresholds_for_level(level: str) -> dict[str, float]:
    """等级 → 阈值副本（未知等级回退默认）。"""
    th = LEVEL_THRESHOLDS.get(level) or LEVEL_THRESHOLDS[_DEFAULT_LEVEL]
    return dict(th)


async def get_effective_thresholds(db, project_id: str) -> dict[str, float]:
    """读取项目当前生效的决策阈值（含开关与缓存逻辑）。"""
    level = await get_effective_level(db, project_id)
    return get_thresholds_for_level(level)


def classify_by_score(score: float, thresholds: dict[str, float], severity: str, level: str = '') -> tuple[str, str]:
    """按阈值分类决策分 → (decision, decision_reason)。纯函数。

    - score >= auto       → auto_fix（直接执行）
    - suggest <= score    → auto_fix（降级 suggestion 模式）
    - score < suggest     → manual（转人工）
    """
    if score >= thresholds['auto']:
        decision = 'auto_fix'
        reason = f'{severity} 问题，评分={score:.2f}，执行自动修复'
    elif score >= thresholds['suggest']:
        decision = 'auto_fix'
        reason = f'{severity} 问题，评分={score:.2f}，降级为 suggestion 模式'
    else:
        decision = 'manual'
        reason = f'{severity} 问题，评分={score:.2f}，风险过大，转人工处理'

    if level:
        reason = f'[{level}] {reason}'
    return decision, reason


# 供外部只读访问当前缓存状态（诊断用）
def cache_info() -> dict[str, Any]:
    return {pid: lvl for pid, (lvl, _) in _level_cache.items()}
