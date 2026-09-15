"""成本预算控制（P0-4：多实例安全的扣费通道）。

设计：
- BudgetStorage 抽象：MVP 用文件原子存储（单进程语义，进程内锁 + tmp+rename 原子写）；
  生产多实例部署时替换为 Redis Lua 原子扣减（见 _REDIS_LUA 注释，接口不变）。
- CostBudget 控制器：按每日累计扣减；daily_max<=0 表示不限额（直接放行不记录）。
- 金额单位：人民币元（与供应商 price_per_image 一致）。

调用方（jobs 创建端点）：
    budget = request.app.state.cost_budget
    ok, total = budget.try_charge(price_per_image)
    if not ok: raise HTTPException(429, ...)
"""

from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# 云端生图单价（元/张）— MVP 常量表；Phase C 供应商报价接入后由供应商能力表替换
PRICE_PER_IMAGE: dict[str, float] = {
    'sansi': 0.03,
    'aliyun': 0.02,
    'tencent': 0.02,
    'openai': 0.04,
}
DEFAULT_PRICE_PER_IMAGE: float = 0.03


# =============================================================================
# 存储抽象
# =============================================================================


class BudgetStorage(ABC):
    """预算存储抽象 — MVP 文件，生产可换 Redis。"""

    @abstractmethod
    def load(self, day: str) -> float:
        """读取某日已用金额（缺省 0.0）。"""

    @abstractmethod
    def save(self, day: str, spent: float) -> None:
        """写入某日已用金额。"""

    @abstractmethod
    def atomic_add(self, day: str, amount: float, max_total: float) -> tuple[bool, float]:
        """原子扣减：当前金额 + amount 超过 max_total 时拒绝（max_total<=0 不限额）。

        Returns:
            (ok, 扣减后总额)；ok=False 时总额为未扣减的当前值。
        """

    def reset_day(self, day: str) -> None:  # noqa: B027 - 供测试/运维可选覆盖
        """清零某日（测试/运维用）。"""


class FileBudgetStorage(BudgetStorage):
    """文件存储 — 进程内锁 + tmp 文件 rename 原子写。

    注意：跨进程/多实例不互斥；生产替换 Redis Lua（见 _REDIS_LUA）。
    """

    _TMP_SUFFIX = '.tmp'

    def __init__(self, path: str | Path = 'data/budget.json'):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: dict[str, float] = self._load_all()

    def load(self, day: str) -> float:
        with self._lock:
            return float(self._data.get(day, 0.0))

    def save(self, day: str, spent: float) -> None:
        with self._lock:
            self._data[day] = float(spent)
            self._flush()

    def atomic_add(self, day: str, amount: float, max_total: float) -> tuple[bool, float]:
        if amount <= 0:
            return True, self.load(day)
        with self._lock:
            current = float(self._data.get(day, 0.0))
            if max_total > 0 and current + amount > max_total:
                return False, current
            new_total = current + amount
            self._data[day] = new_total
            self._flush()
            return True, new_total

    def reset_day(self, day: str) -> None:
        with self._lock:
            self._data.pop(day, None)
            self._flush()

    # ------------------------------------------------------------------

    def _load_all(self) -> dict[str, float]:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, encoding='utf-8') as f:
                raw = json.load(f)
            return {str(k): float(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        except Exception as e:  # noqa: BLE001 - 文件损坏时重建空账本，不 crash
            logger.warning('[VisGuard] 预算文件损坏，重建空账本: %s', e)
            return {}

    def _flush(self) -> None:
        """tmp 文件写入 + rename 原子替换（避免半写文件被读取）。"""
        tmp = self.path.with_suffix(self.path.suffix + self._TMP_SUFFIX)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)


# =============================================================================
# Redis Lua 原子扣减（生产多实例扩展，接口与 BudgetStorage 一致）
# =============================================================================

_REDIS_LUA = """\
-- budget_atomic_add.lua（Phase 2 启用 Redis 存储时使用）
local key = KEYS[1]            -- "budget:YYYY-MM-DD"
local amount = tonumber(ARGV[1])
local max = tonumber(ARGV[2])
local current = tonumber(redis.call('GET', key) or '0')
if max > 0 and (current + amount) > max then
    return {false, current}
end
redis.call('INCRBYFLOAT', key, amount)
redis.call('EXPIRE', key, 86400)   -- 24h TTL
return {true, redis.call('GET', key)}
"""


# =============================================================================
# 控制器
# =============================================================================


class CostBudget:
    """成本预算控制器 — daily_max<=0 时不限额（放行且不扣减）。"""

    def __init__(
        self,
        daily_max: float = 0.0,
        storage: BudgetStorage | None = None,
    ):
        self.daily_max = float(daily_max)
        self.storage = storage or FileBudgetStorage()

    def try_charge(self, amount: float) -> tuple[bool, float]:
        """尝试扣费。

        Returns:
            (ok, 今日已用总额)。不限额（daily_max<=0）时 (True, 0.0) 且不写存储。
        """
        if self.daily_max <= 0:
            return True, 0.0
        today = date.today().isoformat()
        ok, total = self.storage.atomic_add(today, float(amount), self.daily_max)
        if ok:
            logger.info(
                '[VisGuard] 成本扣减: ¥%.2f (今日 ¥%.2f/%.2f)',
                amount, total, self.daily_max,
            )
        else:
            logger.warning(
                '[VisGuard] 预算超限: 今日已达 ¥%.2f/%.2f',
                total, self.daily_max,
            )
        return ok, total

    def today_used(self) -> float:
        """今日已用金额（不限额时 0）。"""
        if self.daily_max <= 0:
            return 0.0
        return self.storage.load(date.today().isoformat())

    def reset_today(self) -> None:
        """清零今日账本（测试/运维）。"""
        self.storage.reset_day(date.today().isoformat())