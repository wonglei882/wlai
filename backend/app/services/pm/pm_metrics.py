"""PM Agent 结构化指标收集器 — 修复成功率/验证通过率/平均耗时/LLM token 消耗。

无需 Prometheus / OpenTelemetry 依赖，用内存计数器实现轻量级指标。
通过 /pm-control/status 的 health.metrics 字段暴露。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from collections import defaultdict

from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PMMetrics:
    """PM Agent 运行指标（文件持久化，进程重启后从快照恢复）。"""

    _SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'pm_metrics_snapshot.json')

    # 修复指标
    fix_attempted: int = 0
    fix_success: int = 0
    fix_failed: int = 0
    fix_partial: int = 0

    # 验证指标
    verify_passed: int = 0
    verify_failed: int = 0

    # LLM 指标
    llm_calls: int = 0
    llm_failures: int = 0
    llm_total_tokens: int = 0

    # P1: token 预算上限（超过则触发降级，避免单次巡检烧光额度）
    # 来源：经验值（DeepSeek-V4 每章节评分约 500-2000 token，
    #        200k ≈ 100~400 次评分调用，足够覆盖 24h 巡检）
    #        进程生命周期累计，非滑动窗口（当前实现为进程级累计）
    LLM_TOKEN_BUDGET: int = 200_000

    # 巡检指标
    scan_rounds: int = 0
    scan_total_projects: int = 0
    scan_total_issues: int = 0

    # 耗时（秒）
    _fix_durations: list[float] = field(default_factory=list)
    _scan_durations: list[float] = field(default_factory=list)

    # 按 issue_type 统计
    _by_type: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: {'fix': 0, 'success': 0, 'fail': 0}))

    def record_fix(self, issue_type: str, result: str, duration_s: float, tokens: int = 0):
        """记录一次修复结果。"""
        self.fix_attempted += 1
        self._by_type[issue_type]['fix'] += 1
        self._fix_durations.append(duration_s)

        if result == 'success':
            self.fix_success += 1
            self._by_type[issue_type]['success'] += 1
        elif result == 'partial':
            self.fix_partial += 1
        else:
            self.fix_failed += 1
            self._by_type[issue_type]['fail'] += 1

        if tokens > 0:
            self.llm_calls += 1
            self.llm_total_tokens += tokens
        self._persist_snapshot()

    def record_verify(self, passed: bool):
        """记录一次验证结果。"""
        if passed:
            self.verify_passed += 1
        else:
            self.verify_failed += 1

    def record_llm_failure(self):
        """记录一次 LLM 调用失败。"""
        self.llm_failures += 1

    def record_scan(self, projects: int, issues: int, duration_s: float):
        """记录一轮巡检。"""
        self.scan_rounds += 1
        self.scan_total_projects += projects
        self.scan_total_issues += issues
        self._scan_durations.append(duration_s)
        self._persist_snapshot()

    def snapshot(self) -> dict:
        """获取指标快照（供 API 返回）。"""
        avg_fix_s = sum(self._fix_durations) / len(self._fix_durations) if self._fix_durations else 0
        avg_scan_s = sum(self._scan_durations) / len(self._scan_durations) if self._scan_durations else 0
        fix_success_rate = (self.fix_success / self.fix_attempted * 100) if self.fix_attempted else 0
        verify_pass_rate = (self.verify_passed / (self.verify_passed + self.verify_failed) * 100) if (self.verify_passed + self.verify_failed) else 0
        llm_failure_rate = (self.llm_failures / self.llm_calls * 100) if self.llm_calls else 0

        return {
            'fix': {
                'attempted': self.fix_attempted,
                'success': self.fix_success,
                'partial': self.fix_partial,
                'failed': self.fix_failed,
                'success_rate': round(fix_success_rate, 1),
                'avg_duration_s': round(avg_fix_s, 2),
            },
            'verify': {
                'passed': self.verify_passed,
                'failed': self.verify_failed,
                'pass_rate': round(verify_pass_rate, 1),
            },
            'llm': {
                'calls': self.llm_calls,
                'failures': self.llm_failures,
                'failure_rate': round(llm_failure_rate, 1),
                'total_tokens': self.llm_total_tokens,
            },
            'scan': {
                'rounds': self.scan_rounds,
                'total_projects': self.scan_total_projects,
                'total_issues': self.scan_total_issues,
                'avg_duration_s': round(avg_scan_s, 2),
            },
            'by_type': {k: dict(v) for k, v in self._by_type.items()},
        }

    def reset(self):
        """重置所有指标（供测试使用）。"""
        self.fix_attempted = 0
        self.fix_success = 0
        self.fix_failed = 0
        self.fix_partial = 0
        self.verify_passed = 0
        self.verify_failed = 0
        self.llm_calls = 0
        self.llm_failures = 0
        self.llm_total_tokens = 0
        self.scan_rounds = 0
        self.scan_total_projects = 0
        self.scan_total_issues = 0
        self._fix_durations.clear()
        self._scan_durations.clear()
        self._by_type.clear()

    def _persist_snapshot(self):
        """将当前计数器持久化到文件（容器重启后可恢复）。"""
        try:
            data = {
                'fix_attempted': self.fix_attempted,
                'fix_success': self.fix_success,
                'fix_failed': self.fix_failed,
                'fix_partial': self.fix_partial,
                'verify_passed': self.verify_passed,
                'verify_failed': self.verify_failed,
                'llm_calls': self.llm_calls,
                'llm_failures': self.llm_failures,
                'llm_total_tokens': self.llm_total_tokens,
                'scan_rounds': self.scan_rounds,
                'scan_total_projects': self.scan_total_projects,
                'scan_total_issues': self.scan_total_issues,
                'by_type': {k: dict(v) for k, v in self._by_type.items()},
            }
            with open(self._SNAPSHOT_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:  # noqa: S110
            pass

    @classmethod
    def _load_snapshot(cls) -> dict:
        """从文件加载上次的计数器快照。"""
        try:
            with open(cls._SNAPSHOT_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    # =====================================================================
    # P1: 指标 → 决策反馈接口（供 self_tuning_strategy 调用，让 metrics 真正闭环）
    # =====================================================================

    def get_type_success_rate(self, issue_type: str, min_samples: int = 3) -> float | None:
        """获取指定 issue_type 的修复成功率（基于内存级近全量样本）。

        Args:
            issue_type: 诊断类型
            min_samples: 最小样本数（少于则返回 None，避免小样本误判）

        Returns:
            成功率 [0.0, 1.0]，样本不足时返回 None
        """
        stats = self._by_type.get(issue_type)
        if not stats:
            return None
        total = stats.get('fix', 0)
        if total < min_samples:
            return None
        success = stats.get('success', 0)
        return success / total

    def is_token_budget_exceeded(self) -> bool:
        """token 预算是否超限（超过 LLM_TOKEN_BUDGET 时返回 True，用于触发降级）。"""
        return self.llm_total_tokens >= self.LLM_TOKEN_BUDGET

    def get_global_fix_success_rate(self, min_samples: int = 5) -> float | None:
        """获取全局修复成功率（所有 issue_type 合并）。"""
        if self.fix_attempted < min_samples:
            return None
        return self.fix_success / self.fix_attempted


# 全局单例（从文件快照恢复，容器重启不归零）
_metrics = PMMetrics()
_restored = PMMetrics._load_snapshot()
if _restored:
    _metrics.fix_attempted = _restored.get('fix_attempted', 0)
    _metrics.fix_success = _restored.get('fix_success', 0)
    _metrics.fix_failed = _restored.get('fix_failed', 0)
    _metrics.fix_partial = _restored.get('fix_partial', 0)
    _metrics.verify_passed = _restored.get('verify_passed', 0)
    _metrics.verify_failed = _restored.get('verify_failed', 0)
    _metrics.llm_calls = _restored.get('llm_calls', 0)
    _metrics.llm_failures = _restored.get('llm_failures', 0)
    _metrics.llm_total_tokens = _restored.get('llm_total_tokens', 0)
    _metrics.scan_rounds = _restored.get('scan_rounds', 0)
    _metrics.scan_total_projects = _restored.get('scan_total_projects', 0)
    _metrics.scan_total_issues = _restored.get('scan_total_issues', 0)
    for _k, _v in _restored.get('by_type', {}).items():
        _metrics._by_type[_k] = defaultdict(lambda: {'fix': 0, 'success': 0, 'fail': 0}, _v)
    logger.info('[PM-Metrics] 从文件快照恢复指标（容器重启恢复）')


def get_pm_metrics() -> PMMetrics:
    """获取 PM 指标单例。"""
    return _metrics
