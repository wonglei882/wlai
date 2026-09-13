"""Prometheus /metrics 指标端点（产品化 P2-2）。

暴露三类指标，供 Prometheus / Grafana 抓取：
- HTTP 请求量 / 延迟直方图（MetricsMiddleware 埋点）
- PM Agent 质量闭环指标：巡检轮次、问题数、修复/验证成功率、LLM token 消耗
  （数据来源 app.services.pm.pm_metrics 单例，进程重启后从快照恢复）
- 系统资源指标：进程 RSS 内存、CPU 使用率、文件句柄数、线程数（psutil）

抓取方式（默认无认证，符合 scrape 协议，仅建议内网暴露）：
    GET /metrics
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request, Response

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=['metrics'])


# =============================================================================
# 独立注册表（避免与默认注册表 / 其他库冲突）
# =============================================================================
REGISTRY = CollectorRegistry()

# ── HTTP 埋点指标（MetricsMiddleware 更新） ────────────────────────────────
http_requests_total = Counter(
    'wlai_http_requests_total',
    'HTTP 请求总数',
    ['method', 'path', 'status'],
    registry=REGISTRY,
)
http_request_duration_seconds = Histogram(
    'wlai_http_request_duration_seconds',
    'HTTP 请求耗时（秒）',
    ['method', 'path'],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

# ── PM Agent 质量闭环指标（scrape 时从 pm_metrics 单例回填） ───────────────
pm_scan_rounds = Gauge('wlai_pm_scan_rounds', 'PM 巡检轮次（累计）', registry=REGISTRY)
pm_scan_projects = Gauge('wlai_pm_scan_projects', 'PM 巡检覆盖项目数（累计）', registry=REGISTRY)
pm_scan_issues = Gauge('wlai_pm_scan_issues', 'PM 巡检累计发现问题数', registry=REGISTRY)
pm_fix_attempted = Gauge('wlai_pm_fix_attempted', 'PM 修复尝试次数（累计）', registry=REGISTRY)
pm_fix_success = Gauge('wlai_pm_fix_success', 'PM 修复成功次数（累计）', registry=REGISTRY)
pm_fix_partial = Gauge('wlai_pm_fix_partial', 'PM 修复部分成功次数（累计）', registry=REGISTRY)
pm_fix_failed = Gauge('wlai_pm_fix_failed', 'PM 修复失败次数（累计）', registry=REGISTRY)
pm_verify_passed = Gauge('wlai_pm_verify_passed', 'PM 验证通过次数（累计）', registry=REGISTRY)
pm_verify_failed = Gauge('wlai_pm_verify_failed', 'PM 验证失败次数（累计）', registry=REGISTRY)
pm_llm_calls = Gauge('wlai_pm_llm_calls', 'PM LLM 调用次数（累计）', registry=REGISTRY)
pm_llm_failures = Gauge('wlai_pm_llm_failures', 'PM LLM 调用失败次数（累计）', registry=REGISTRY)
pm_llm_tokens = Gauge('wlai_pm_llm_tokens', 'PM LLM token 消耗（累计）', registry=REGISTRY)
pm_fix_success_rate = Gauge('wlai_pm_fix_success_rate', 'PM 修复成功率（0-100）', registry=REGISTRY)
pm_verify_pass_rate = Gauge('wlai_pm_verify_pass_rate', 'PM 验证通过率（0-100）', registry=REGISTRY)

# ── 系统资源指标 ────────────────────────────────────────────────────────────
process_rss_bytes = Gauge('wlai_process_rss_bytes', '进程常驻内存（字节）', registry=REGISTRY)
process_cpu_percent = Gauge('wlai_process_cpu_percent', '进程 CPU 使用率（%）', registry=REGISTRY)
process_open_fds = Gauge('wlai_process_open_fds', '进程打开文件句柄数', registry=REGISTRY)
process_threads = Gauge('wlai_process_threads', '进程线程数', registry=REGISTRY)


class MetricsMiddleware:
    """HTTP 请求埋点中间件：统计请求量与延迟直方图。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        request = Request(scope)
        start = time.perf_counter()
        status_holder = {'code': 500}

        async def _send_wrapper(message):
            if message['type'] == 'http.response.start':
                status_holder['code'] = message['status']
            await send(message)

        try:
            await self.app(scope, receive, _send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            label_path = request.url.path
            http_requests_total.labels(request.method, label_path, str(status_holder['code'])).inc()
            http_request_duration_seconds.labels(request.method, label_path).observe(elapsed)


def _update_pm_gauges() -> None:
    """从 pm_metrics 单例回填 PM 质量闭环指标。"""
    try:
        from app.services.pm.pm_metrics import get_pm_metrics

        snap = get_pm_metrics().snapshot()
        pm_scan_rounds.set(snap['scan']['rounds'])
        pm_scan_projects.set(snap['scan']['total_projects'])
        pm_scan_issues.set(snap['scan']['total_issues'])
        pm_fix_attempted.set(snap['fix']['attempted'])
        pm_fix_success.set(snap['fix']['success'])
        pm_fix_partial.set(snap['fix']['partial'])
        pm_fix_failed.set(snap['fix']['failed'])
        pm_verify_passed.set(snap['verify']['passed'])
        pm_verify_failed.set(snap['verify']['failed'])
        pm_llm_calls.set(snap['llm']['calls'])
        pm_llm_failures.set(snap['llm']['failures'])
        pm_llm_tokens.set(snap['llm']['total_tokens'])
        pm_fix_success_rate.set(snap['fix']['success_rate'])
        pm_verify_pass_rate.set(snap['verify']['pass_rate'])
    except Exception as e:  # noqa: BLE001 - 指标回填失败不影响 scrape
        logger.debug('[Metrics] PM 指标回填失败: %s', e)


def _update_system_gauges() -> None:
    """进程级系统资源指标。"""
    try:
        import psutil

        proc = psutil.Process()
        process_rss_bytes.set(proc.memory_info().rss)
        try:
            process_cpu_percent.set(proc.cpu_percent(interval=None))
        except Exception:  # noqa: BLE001
            pass
        try:
            process_open_fds.set(len(proc.open_files()))
        except Exception:  # noqa: BLE001
            pass
        process_threads.set(proc.num_threads())
    except Exception:  # noqa: BLE001 - psutil 不可用时静默跳过系统指标
        pass


@router.get('/metrics', include_in_schema=False)
async def metrics() -> Response:
    """Prometheus 文本格式指标输出。"""
    _update_pm_gauges()
    _update_system_gauges()
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
