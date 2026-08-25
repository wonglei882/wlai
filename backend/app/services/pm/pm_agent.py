"""
PM Agent — 后台定期巡检服务
每 30 分钟扫描所有活跃项目的一致性状态，主动发现并记录问题。

巡检维度（SCAN_REGISTRY）：
1. 角色状态一致性：检测相邻章节间的角色位置/状态跳变
2. 伏笔老化检测：planted 但超过 N 章仍未 resolved 的伏笔
3. 世界观规则漂移：相邻章节的世界设定描述发生实质性变化
4. 大纲漂移：章节大纲结构与前序大纲相比发生实质性变化
5. 质量评分：对最新章节执行 7 维 AI/规则评分（pacing/dialogue/hook/...）
6. 段落格式：检测超长段落（>110 字/段），触发 format_webnovel_paragraphs 重排

空转优化：连续 2 轮无 issue 无新章节 -> 间隔从 30min 降频为 2h

使用独立的 system 会话执行，不影响在线请求。

架构：扫描函数与注册表已拆分到 pm_scanners.py；本模块保留
巡检编排、决策驱动、生命周期管理。
"""

import asyncio
import math
import time
import uuid

from sqlalchemy import select, func, text
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_engine
from app.logger import get_logger
from app.models.pm_decision_log import PMDecisionLog
from app.services.pm.feature_config import pm_feature_config
from app.services.pm.pm_agent_decision import classify_severity_by_type, diagnose_and_fix
from app.services.pm.pm_runtime_state import PMRuntimeState, runtime_state

# 扫描函数与 SCAN_REGISTRY 注册表已移至 pm_scanners.py（控制文件行数 < 800）
# 通过 import 触发 pm_scanners 模块加载，使其 @scan_dimension 装饰器填充 SCAN_REGISTRY
from app.services.pm.pm_scanners import (  # noqa: F401
    SCAN_REGISTRY,
    _write_diagnostic_from_scan,
)

# ===== Q7：SCAN_REGISTRY 反向映射 {issue_type → dimension_name} =====
# 启动时构建一次，避免 _scan_single_project 对每个 issue 做 O(n) 列表推导。
_SCAN_ISSUE_TO_NAME: dict = {}
for _dim_name, _dim_meta in SCAN_REGISTRY.items():
    _SCAN_ISSUE_TO_NAME[_dim_meta['issue_type']] = _dim_name

logger = get_logger(__name__)

# 巡检参数从 pm_features.yaml 读取（feature_config 单例），避免"配置写了不用"
_inspection_cfg = pm_feature_config.get_feature_config('core.inspection')
_perf_cfg = pm_feature_config.get_performance()

# 巡检间隔（秒）
SCAN_INTERVAL_SECONDS = int(_inspection_cfg.get('interval_minutes', 30)) * 60  # 30 分钟
# 单轮巡检总超时（秒）：超过则跳过本轮，防止 handler 卡死拖住循环
SCAN_TIMEOUT_SECONDS = int(_perf_cfg.get('scan_timeout_seconds', 300))
# 单轮问题上限：超过则降级为只读（pm_features.yaml: performance.max_issues_per_round）
MAX_ISSUES_PER_ROUND = int(_perf_cfg.get('max_issues_per_round', 100))
# 问题数超过此值时调用 LLM 排序（pm_features.yaml: performance.decompose_threshold）
DECOMPOSE_THRESHOLD = int(_perf_cfg.get('decompose_threshold', 3))
# 每 N 轮巡检清理一次历史日志（默认 48 轮 ≈ 24h）
CLEANUP_EVERY_ROUNDS = int(_perf_cfg.get('cleanup_every_rounds', 48))
# 主动汇报器配置（pm_features.yaml: optional.proactive_reporter）
# 巡检发现问题后调用 ProactiveReporter.check() 生成预警，写入前端诊断面板。
_proactive_cfg = pm_feature_config.get_feature_config('optional.proactive_reporter')
_PROACTIVE_ENABLED = bool(_proactive_cfg.get('enabled', True))
_PROACTIVE_DEDUP_HOURS = int(_proactive_cfg.get('dedup_hours', 1))
_PROACTIVE_PERSIST_SUGGESTIONS = bool(_proactive_cfg.get('persist_suggestions', True))

# 巡检循环异常最大自动重启次数（崩溃保护上限）
_MAX_CRASH_RESTART = 3
# P0.4: 连续空闲 N 轮后降频倍数（2 → 间隔 × 4 = 30min → 2h）
# 阈值/倍率来自 pm_features.yaml: performance.idle_*
IDLE_THRESHOLD_ROUNDS = _perf_cfg.get('idle_threshold_rounds', 2)
IDLE_INTERVAL_MULTIPLIER = _perf_cfg.get('idle_interval_multiplier', 4)

# 注：可变运行时状态（巡检任务引用/上次扫描时间/空闲计数/崩溃计数/章节计数/每日汇总节流等）
# 已收拢至 pm_runtime_state.PMRuntimeState 单例（runtime_state），本模块不再声明模块级全局变量。


def _compute_idle_interval(idle_rounds: int) -> int:
    """空闲轮数 → 间隔倍数，对数渐变（2轮×2, 3轮×3, 4轮×4, 5轮×4封顶）。"""
    if idle_rounds < 2:
        return 1
    return min(4, int(math.log2(idle_rounds)) + 1)


def _next_sleep_seconds(round_completed: bool, round_issues: int, has_new_chapters: bool) -> int:
    """P0.4 动态间隔的纯决策：只有正常完成且干净的轮次才累计空闲（异常/超时轮保持满频）。"""
    idle_rounds = runtime_state.consecutive_idle_rounds
    if round_issues > 0 or has_new_chapters:
        runtime_state.consecutive_idle_rounds = 0
        return SCAN_INTERVAL_SECONDS
    if not round_completed:
        if idle_rounds:
            logger.warning('[PM-Agent] 本轮巡检未正常完成（异常/超时），空闲计数清零保持满频巡检')
        runtime_state.consecutive_idle_rounds = 0
        return SCAN_INTERVAL_SECONDS
    runtime_state.consecutive_idle_rounds = idle_rounds + 1
    multiplier = _compute_idle_interval(runtime_state.consecutive_idle_rounds)
    if multiplier > 1:
        logger.info(f'[PM-Agent] 连续 {runtime_state.consecutive_idle_rounds} 轮无 issue，降频×{multiplier}（{SCAN_INTERVAL_SECONDS * multiplier // 60} 分钟）')
        return SCAN_INTERVAL_SECONDS * multiplier
    return SCAN_INTERVAL_SECONDS


def _infer_severity(issue_type: str) -> str:
    """根据问题类型推断严重性（统一使用 pm_agent_decision.classify_severity_by_type）。"""
    return classify_severity_by_type(issue_type)


# =============================================================================
# 单项目全量巡检
# =============================================================================


async def _scan_single_project(db: AsyncSession, project_id: str, user_id: str) -> dict[str, Any]:
    """对单个项目执行全量巡检 → 诊断决策 → 自动修复 → 验证。

    遍历 SCAN_REGISTRY 中所有注册的诊断维度，执行扫描并收集问题。
    对每个问题写入 diagnostic_log 并调用 diagnose_and_fix 进行决策与修复。

    Args:
        db: 数据库会话（AsyncSession）
        project_id: 项目ID
        user_id: 用户ID（用于权限/上下文）

    Returns:
        Dict[str, Any]: {
            "issues": {维度名: [问题列表]},
            "decisions": [决策结果列表]
        }
    """
    all_issues: dict[str, list] = {name: [] for name in SCAN_REGISTRY}
    decisions = []  # 决策结果列表

    # 本轮巡检 round id（用于决策日志去重）
    scan_round = str(uuid.uuid4())

    # 数据驱动：遍历注册表执行所有诊断维度
    for name, meta in SCAN_REGISTRY.items():
        try:
            all_issues[name] = await meta['fn'](db, project_id, user_id)
        except Exception as scan_err:
            logger.error(f'[PM-Agent] 维度 {name} 扫描异常: {scan_err}', extra={'project_id': project_id, 'scan_dimension': name})
            await db.rollback()  # 维度间事务隔离：中止被毒化的 aborted 事务，保住后续维度（循环期只读，无回滚损失）
            all_issues[name] = []

    # 写入 diagnostic_log（历史记录），并对每个问题做决策
    total_issues = sum(len(v) for v in all_issues.values())
    # 只读降级：问题数超过 MAX_ISSUES_PER_ROUND 时只写诊断、不执行修复
    read_only = total_issues > MAX_ISSUES_PER_ROUND
    if read_only:
        logger.warning(f'[PM-Agent] 项目 {project_id[:8]} 问题数 {total_issues} 超过上限 {MAX_ISSUES_PER_ROUND}，降级为只读（仅记录诊断不修复）')
    if total_issues > 0:
        # ===== 新增：目标分解（问题数 > 3 时调用 LLM 排序） =====
        flat_issues = []
        for name, meta in SCAN_REGISTRY.items():
            issue_type = meta['issue_type']
            for issue in all_issues[name]:
                issue['type'] = issue_type
                issue['severity'] = issue.get('severity') or _infer_severity(issue_type)
                flat_issues.append(issue)

        # 问题数超过 DECOMPOSE_THRESHOLD 时调用 LLM 分解优先级
        if len(flat_issues) > DECOMPOSE_THRESHOLD:
            try:
                from app.services.pm.pm_agent_decision import _decompose_repair_priority

                flat_issues, reasoning = await _decompose_repair_priority(db, flat_issues, project_id, user_id)
                logger.info(f'[PM-Agent 目标分解] 项目 {project_id[:8]} 问题数 {len(flat_issues)}，已由 LLM 排序，理由: {reasoning[:50]}')
                # 将推理链附加到每个 issue
                for issue in flat_issues:
                    issue['llm_reasoning'] = reasoning
            except Exception as decomp_e:
                logger.warning(f'[PM-Agent 目标分解] 调用失败（使用原始顺序）: {decomp_e}')

        # 处理排序后的问题列表
        for issue in flat_issues:
            issue_type = issue.get('type', '')
            _dim_name = _SCAN_ISSUE_TO_NAME.get(issue_type)
            _reg = SCAN_REGISTRY.get(_dim_name, {}) if _dim_name else None
            diag_msg_fn = _reg.get('diag_msg_fn') if _reg else None
            diag_msg = diag_msg_fn(issue) if diag_msg_fn else issue.get('message', '')
            # 提取章节号（优先 chapter 字段，回退到各维度特有字段）
            chapter_num = (
                issue.get('chapter')
                or issue.get('chapter_number')
                or issue.get('planted_chapter')
                or issue.get('from_chapter')
                or _extract_chapter_from_range(issue.get('chapter_range', ''))
                or 0
            )
            await _write_diagnostic_from_scan(
                db,
                project_id,
                user_id,
                issue_type,
                chapter_num,
                diag_msg,
                issue,
            )
            if read_only:
                # 只读降级：不执行修复，记录 skip 决策
                decisions.append(
                    {
                        'fix_attempted': False,
                        'verified': False,
                        'decision': 'skip_readonly',
                        'decision_reason': f'只读降级：问题数 {total_issues} 超过上限 {MAX_ISSUES_PER_ROUND}',
                    }
                )
                continue
            decision = await diagnose_and_fix(
                db,
                issue,
                project_id,
                user_id,
                scan_round,
                total_issues_in_scan=len(all_issues),
            )
            decisions.append(decision)

    return {'issues': all_issues, 'decisions': decisions}


def _extract_chapter_from_range(chapter_range: str):
    """从 '第12章→第15章' 提取起始章节号。"""
    try:
        if '→' in chapter_range:
            start = chapter_range.split('→')[0].strip().lstrip('第').rstrip('章')
            return int(start) if start.isdigit() else 0
    except ValueError:
        pass
    return 0


# =============================================================================
# 全量巡检（扫描所有活跃项目）
# =============================================================================


def _log_round_summary(*, issues_projects: int, total_issues: int, decisions: int, fixed: int, verified: int, elapsed_s: float) -> None:
    """每轮巡检无条件输出的 INFO 心跳——静默失效的唯一防线，勿降级为 debug。"""
    logger.info(
        '[PM-Agent] 本轮巡检完成: 扫描 %s 项目/%s 章节, %s 项目有问题, 发现 %s 问题, 决策 %s 次, 修复 %s 次, 验证通过 %s 次, 耗时 %.1fs',
        runtime_state.last_round_stats.get('scanned_projects', 0),
        runtime_state.last_round_stats.get('scanned_chapters', 0),
        issues_projects,
        total_issues,
        decisions,
        fixed,
        verified,
        elapsed_s,
    )
    # 指标埋点：巡检轮次/覆盖项目/问题数/耗时（此前 record_scan 已定义但从未接线）
    try:
        from app.services.pm.pm_metrics import _metrics

        _metrics.record_scan(
            runtime_state.last_round_stats.get('scanned_projects', 0),
            total_issues,
            elapsed_s,
        )
    except Exception as me:
        logger.debug(f'[PM-Agent] record_scan 埋点失败（非阻塞）: {me}')


async def scan_all_projects() -> dict[str, Any]:
    """扫描所有有章节记录的项目，执行全量巡检并自动修复。

    使用 system 会话（不依赖特定用户），遍历所有项目。
    对每个项目调用 _scan_single_project 完成：诊断 → 决策 → 自动修复 → 验证。

    Returns:
        Dict[str, Any]: {project_id: {"issues": {...}, "decisions": [...]}}
        仅包含有问题的项目（total_issues > 0 的项目才入结果）。
    """
    from app.agent.domain.odd_config import check_odd_boundary

    engine = await get_engine('system')
    from sqlalchemy.ext.asyncio import async_sessionmaker

    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 先查所有有章节的项目 ID（批量获取，消除N+1）
    async with AsyncSessionLocal() as db:
        projects_result = await db.execute(
            text(
                'SELECT DISTINCT c.project_id, p.user_id, p.title, '
                '(SELECT COUNT(*) FROM chapters ch WHERE ch.project_id = c.project_id) as chapter_count '
                'FROM chapters c '
                'JOIN projects p ON p.id = c.project_id '
                "WHERE c.project_id IS NOT NULL AND c.project_id != ''"
            )
        )
        project_map = {}
        for row in projects_result.fetchall():
            project_map[row[0]] = {'user_id': row[1], 'title': row[2], 'chapter_count': row[3]}

        runtime_state.last_round_stats = {
            'scanned_projects': len(project_map),
            'scanned_chapters': sum(int(info.get('chapter_count') or 0) for info in project_map.values()),
        }

    if not project_map:
        return {}

    runtime_state.last_round_degraded_count = 0

    async def _scan_one(project_id: str, project_info: dict):
        """单个项目巡检（独立 session，可并行）。"""
        try:
            # 新增：ODD 边界检查
            odd_result = check_odd_boundary(
                project={'id': project_id, 'type': 'novel_project', 'chapter_count': project_info['chapter_count']},
                issues=None,  # 扫描前还不知道问题数
            )

            if not odd_result['in_odd']:
                logger.warning(f'[PM-Agent] 项目 {project_id[:8]} 超出 ODD 边界: {odd_result["violations"]}')
                # ODD 外降级为跳过
                if odd_result['degraded_mode'] == 'skip_round':
                    return None

            async with AsyncSessionLocal() as db:
                scan_result = await _scan_single_project(db, project_id, project_info['user_id'])
                issues = scan_result.get('issues', scan_result)
                total = sum(len(v) for v in issues.values())

                # 只读降级逻辑已在 _scan_single_project 内基于 MAX_ISSUES_PER_ROUND 实现
                if total > MAX_ISSUES_PER_ROUND:
                    runtime_state.last_round_degraded_count += 1

                if total > 0:
                    logger.info(
                        f'[PM-Agent] 项目 {project_id[:8]} 巡检: '
                        f'角色={len(issues.get("character_consistency", []))} '
                        f'伏笔老化={len(issues.get("foreshadow_age", []))} '
                        f'世界观漂移={len(issues.get("world_rule_drift", []))} '
                        f'大纲漂移={len(issues.get("outline_drift", []))}'
                    )
                    # 接线：巡检发现问题后触发主动汇报器，将预警写入前端诊断面板
                    # （之前 ProactiveReporter / generate_proactive_suggestions 从未被调用）
                    await _run_proactive_report(project_id, project_info['user_id'], total)
                    return project_id, scan_result
        except Exception as e:
            logger.error(
                f'[PM-Agent] 项目扫描失败 {project_id[:8]}: {e}', extra={'project_id': project_id, 'user_id': project_info.get('user_id', '')}
            )
            await _write_system_alert(project_id, project_info.get('user_id', ''), f'项目巡检失败: {e}')
        return None

    # 项目并行扫描（每项目独立 session，DB 连接池内安全）
    results = {}
    scan_tasks = [_scan_one(pid, info) for pid, info in project_map.items()]
    for r in await asyncio.gather(*scan_tasks):
        if r:
            results[r[0]] = r[1]

    return results


async def _write_system_alert(project_id: str, user_id: str, message: str):
    """巡检异常告警：双写 PMDecisionLog（审计）+ PMDiagnosticLog（前端可见）。

    1 小时内同项目同类型未解决告警去重，避免刷屏。
    """
    try:
        engine = await get_engine('system')
        from sqlalchemy.ext.asyncio import async_sessionmaker

        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        from datetime import timedelta

        async with AsyncSessionLocal() as db:
            # 去重：1h 内同项目已有未解决的系统告警则跳过
            dup = await db.execute(
                select(func.count())
                .select_from(PMDecisionLog)
                .where(
                    PMDecisionLog.project_id == project_id,
                    PMDecisionLog.diag_type == 'pm_system_alert',
                    PMDecisionLog.created_at >= datetime.now() - timedelta(hours=1),
                )
            )
            if (dup.scalar_one() or 0) > 0:
                return

            db.add(
                PMDecisionLog(
                    project_id=project_id,
                    user_id=user_id,
                    diag_type='pm_system_alert',
                    severity='critical',
                    original_message=(message or '')[:500],
                    decision='alert',
                    decision_reason='巡检异常自动告警',
                    fix_result='failed',
                    fix_attempted=False,
                    verified=False,
                    verify_message=message,
                )
            )
            # 前端 PM 预警仪表盘可见（summary 接口基于诊断表）
            from app.models.pm_diagnostic_log import PMDiagnosticLog

            db.add(
                PMDiagnosticLog(
                    project_id=project_id,
                    user_id=user_id,
                    diag_type='pm_system_alert',
                    severity='critical',
                    message=(message or '')[:500],
                    suggestion='请检查容器/数据库状态，或查看后端日志定位巡检异常',
                    resolved=False,
                )
            )
            await db.commit()
    except Exception as e:
        logger.warning(f'[PM-Agent] 写系统告警失败: {e}')


# =============================================================================
# 主动汇报器接线 — 巡检发现问题后生成预警报告，写入前端诊断面板
# 闭环：扫描修复 → 写 PMDecisionLog（审计）→ 本函数生成预警 → 写
# PMDiagnosticLog（前端 /pm-diagnostic-logs 可见）→ 用户感知。
# 之前 ProactiveReporter.check() / generate_proactive_suggestions() 从未被调用，
# 等于盖了整套通知系统但未通电；本函数即为通电接线。
# =============================================================================


async def _run_proactive_report(project_id: str, user_id: str, total_issues: int) -> None:
    """巡检发现问题后触发主动汇报器，将预警写入前端可见的诊断面板。

    非阻塞：任何异常仅记录日志，不影响巡检主流程。使用独立 db session，
    与扫描会话隔离（同 _write_system_alert 的处理范式）。
    """
    if not _PROACTIVE_ENABLED:
        return
    try:
        from app.services.proactive_reporter import reporter as _reporter
        from app.services.proactive_suggestions import generate_proactive_suggestions
        from app.models.pm_diagnostic_log import PMDiagnosticLog
        from datetime import timedelta

        engine = await get_engine('system')
        from sqlalchemy.ext.asyncio import async_sessionmaker

        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with AsyncSessionLocal() as db:
            written = 0

            async def _persist(diag_type, severity, msg, suggestion='', chapter_number=None):
                """去重后写入一条 PMDiagnosticLog，返回是否写入。"""
                nonlocal written
                dup = await db.execute(
                    select(func.count())
                    .select_from(PMDiagnosticLog)
                    .where(
                        PMDiagnosticLog.project_id == project_id,
                        PMDiagnosticLog.diag_type == diag_type,
                        PMDiagnosticLog.resolved.is_(False),
                        PMDiagnosticLog.created_at >= datetime.now() - timedelta(hours=_PROACTIVE_DEDUP_HOURS),
                    )
                )
                if (dup.scalar_one() or 0) > 0:
                    return False
                db.add(
                    PMDiagnosticLog(
                        project_id=project_id,
                        user_id=user_id,
                        diag_type=diag_type,
                        severity=severity,
                        message=(msg or '')[:500],
                        suggestion=(suggestion or '')[:500],
                        chapter_number=chapter_number,
                        resolved=False,
                        created_at=datetime.now(),
                    )
                )
                written += 1
                return True

            # 1. 生成预警报告（LongNovelGuardian + OOC 未解决违规，聚合为 critical/high）
            report = await _reporter.check(project_id, user_id, db)
            for item in report.items:
                await _persist(
                    item.type,
                    'critical' if item.severity in ('critical', 'high') else 'warning',
                    item.msg,
                    item.suggestion,
                    item.chapter_number,
                )

            # 2. 里程碑检测（每 10 章触发一次，之前 milestone_check() 零调用）
            try:
                milestone_report = await _reporter.milestone_check(project_id, user_id, db)
                if milestone_report:
                    for item in milestone_report.items:
                        await _persist(
                            item.type,
                            'warning' if item.severity == 'low' else 'critical',
                            item.msg,
                            item.suggestion,
                            item.chapter_number,
                        )
            except Exception as me:
                logger.debug(f'[PM-Agent] milestone_check 失败（非阻塞）: {me}')

            # 3. 每日汇总（24h 节流；只取 daily_stats 项，跳过其内部 check 预警避免重复扫描）
            now = datetime.now()
            last = runtime_state.last_daily_summary.get(project_id)
            if last is None or (now - last) >= timedelta(hours=24):
                try:
                    daily_report = await _reporter.daily_summary(project_id, user_id, db)
                    for item in daily_report.items:
                        if item.type == 'daily_stats':
                            await _persist(item.type, 'warning', item.msg, item.suggestion, item.chapter_number)
                    runtime_state.last_daily_summary[project_id] = now
                except Exception as de:
                    logger.debug(f'[PM-Agent] daily_summary 失败（非阻塞）: {de}')

            # 4. 生成主动建议（内容偏短/伏笔过多/主角缺场/字数下降）
            if _PROACTIVE_PERSIST_SUGGESTIONS:
                suggestions = await generate_proactive_suggestions(project_id, db)
                for s in suggestions:
                    if s.get('priority') == 'low':
                        continue  # 低优先级建议不写入面板，避免噪声
                    s_type = s.get('type', 'proactive_tip')
                    details = s.get('details') or []
                    detail_str = ' | '.join(str(d)[:80] for d in details[:3]) if details else ''
                    await _persist(
                        s_type,
                        'critical' if s.get('priority') == 'high' else 'warning',
                        s.get('message', ''),
                        detail_str[:500] if detail_str else '',
                    )

            if written > 0:
                await db.commit()
                logger.info(f'[PM-Agent] 主动汇报器写入 {written} 条预警至诊断面板 (project={project_id[:8]}, scan_issues={total_issues})')
    except Exception as e:
        logger.warning(f'[PM-Agent] 主动汇报器执行失败（非阻塞）: {e}', exc_info=True)


# =============================================================================
# 巡检循环
# =============================================================================


async def pm_agent_loop():
    """PM Agent 后台巡检循环：每 SCAN_INTERVAL_SECONDS 执行一次全量扫描。"""
    from app.api.pm_control import PMControlState

    logger.info(f'[PM-Agent] 巡检循环启动（间隔 {SCAN_INTERVAL_SECONDS // 60} 分钟）')
    try:
        while True:
            # 新增：Kill Switch 检查
            if PMControlState.is_killed():
                logger.warning('[PM-Agent] Kill Switch 已触发，停止巡检循环')
                break

            # 新增：Pause 检查（暂停时等待 10s 后重试）
            while PMControlState.is_paused():
                logger.debug('[PM-Agent] 已暂停，等待恢复...')
                await asyncio.sleep(10)
                if PMControlState.is_killed():
                    logger.warning('[PM-Agent] 暂停期间收到 Kill，停止巡检循环')
                    break

            # —— Leader Lock：多实例部署时仅 leader 实例执行扫描（单实例下恒为真）——
            # fail-open：锁检查异常时按单实例继续，保证单容器部署行为不变
            _is_leader = True
            try:
                from sqlalchemy.ext.asyncio import async_sessionmaker

                _lock_engine = await get_engine('system')
                _LockSession = async_sessionmaker(_lock_engine, class_=AsyncSession, expire_on_commit=False)
                from app.services.pm.pm_leader_lock import (
                    get_holder_id as _get_holder_id,
                    try_acquire_leadership as _try_acquire,
                )

                async with _LockSession() as _lock_db:
                    _is_leader = await _try_acquire(
                        _lock_db,
                        _get_holder_id(),
                        ttl_seconds=SCAN_INTERVAL_SECONDS * 2,
                    )
            except Exception as _lock_err:
                logger.warning(f'[PM-Agent] leader lock 检查失败，按单实例继续: {_lock_err}')
                _is_leader = True
            if not _is_leader:
                logger.info('[PM-Agent] 非 leader 实例，本轮跳过扫描')
                await asyncio.sleep(SCAN_INTERVAL_SECONDS)
                continue

            _round_completed = False  # RC5 防线：异常/超时路径不得计入"干净空闲"降频计数
            result: dict[str, Any] = {}  # 提前声明：异常/超时路径不再依赖 locals() 探测
            try:
                _round_started = time.monotonic()
                result = await asyncio.wait_for(scan_all_projects(), timeout=SCAN_TIMEOUT_SECONDS)
                total_projects = len(result)
                total_issues = 0
                total_decisions = 0
                fixed_count = 0
                verified_count = 0
                for _project_id, scan_result in result.items():
                    issues = scan_result.get('issues', {})
                    decisions = scan_result.get('decisions', [])
                    total_issues += sum(len(v) for v in issues.values())
                    total_decisions += len(decisions)
                    for d in decisions:
                        if d.get('fix_attempted'):
                            fixed_count += 1
                        if d.get('verified'):
                            verified_count += 1
                _log_round_summary(
                    issues_projects=total_projects,
                    total_issues=total_issues,
                    decisions=total_decisions,
                    fixed=fixed_count,
                    verified=verified_count,
                    elapsed_s=time.monotonic() - _round_started,
                )

                # 记录巡检完成时间戳（供健康检查判断循环是否存活）
                runtime_state.last_scan_at = time.time()

                # 每 CLEANUP_EVERY_ROUNDS 轮（默认 48 ≈ 24h）清理一次历史日志
                _scan_round_count = getattr(pm_agent_loop, '_round_count', 0) + 1
                pm_agent_loop._round_count = _scan_round_count
                if _scan_round_count % CLEANUP_EVERY_ROUNDS == 0:
                    try:
                        await _cleanup_old_logs()
                    except Exception as cleanup_e:
                        logger.warning(f'[PM-Agent] 日志清理失败（非阻塞）: {cleanup_e}')

                _round_completed = True
            except TimeoutError:
                logger.error(f'[PM-Agent] 巡检超时（>{SCAN_TIMEOUT_SECONDS}s），跳过本轮')
                await _write_system_alert('', '', f'巡检超时（>{SCAN_TIMEOUT_SECONDS}s），已跳过本轮')
            except Exception as e:
                logger.warning(f'[PM-Agent] 巡检循环异常: {e}')

            # P0.4: 动态巡检间隔 — 连续无 issue 自动降频，有新章节恢复；异常/超时轮清零计数
            total_round_issues = 0
            _scan_data = result  # try 前置初值 {}，异常/超时轮安全
            for _pid, _result in _scan_data.items():
                total_round_issues += sum(len(v) for v in _result.get('issues', {}).values())

            # 检测本轮是否有新章节（与上一轮比）
            _has_new_chapters = False
            _current_counts: dict[str, int] = {}
            for _pid in _scan_data:
                _result = _scan_data[_pid]
                # 从 issues 的 chapter_number 推断最新章号
                _max_ch = 0
                for _issues_list in _result.get('issues', {}).values():
                    for _iss in _issues_list:
                        _ch = _iss.get('chapter_number', 0) or _iss.get('chapter', 0)
                        if isinstance(_ch, (int, float)) and _ch > _max_ch:
                            _max_ch = int(_ch)
                _current_counts[_pid] = _max_ch
                _prev = runtime_state.last_round_chapter_counts.get(_pid, 0)
                if _max_ch > _prev:
                    _has_new_chapters = True

            runtime_state.last_round_chapter_counts = _current_counts

            _sleep_seconds = _next_sleep_seconds(_round_completed, total_round_issues, _has_new_chapters)

            await asyncio.sleep(_sleep_seconds)

    except asyncio.CancelledError:
        logger.info('[PM-Agent] 巡检循环已停止')


# =============================================================================
# 生命周期管理（供 main.py lifespan 调用）
# =============================================================================


def register_pm_agent():
    """在应用启动时注册 PM Agent 后台巡检任务（含自动重启保护）。"""
    # 从文件恢复 Kill/Pause 状态（防止进程重启后 Kill Switch "复活"）
    from app.api.pm_control import PMControlState

    PMControlState.init_from_file()

    # 显式注册所有修复 handler（消除模块加载副作用）
    from app.services.pm.pm_fix_handlers import register_pm_handlers

    register_pm_handlers()

    # 启动时校验注册维度（避免模块加载时循环导入）
    validate_registry()

    if runtime_state.pm_agent_task is None or runtime_state.pm_agent_task.done():
        runtime_state.loop_crash_count = 0
        runtime_state.pm_agent_task = asyncio.create_task(_supervised_pm_agent_loop())
        logger.info('[PM-Agent] PM Agent 后台巡检任务已注册（含自动重启监督）')
    else:
        logger.debug('[PM-Agent] PM Agent 已在运行，跳过注册')


async def _supervised_pm_agent_loop():
    """监督包装器：pm_agent_loop 异常退出时自动重启（最多 _MAX_CRASH_RESTART 次）。"""
    while runtime_state.loop_crash_count < _MAX_CRASH_RESTART:
        try:
            await pm_agent_loop()
            # 正常退出（Kill Switch 或 CancelledError）
            break
        except asyncio.CancelledError:
            logger.info('[PM-Agent] 巡检循环被取消（应用关闭）')
            raise
        except Exception as e:
            runtime_state.loop_crash_count += 1
            logger.error(
                f'[PM-Agent] 巡检循环异常退出 (crash {runtime_state.loop_crash_count}/{_MAX_CRASH_RESTART}): {e}',
                exc_info=True,
            )
            if runtime_state.loop_crash_count < _MAX_CRASH_RESTART:
                logger.info('[PM-Agent] 将在 30s 后自动重启巡检循环')
                await asyncio.sleep(30)
            else:
                logger.error('[PM-Agent] 达到最大重启次数，停止自动重启')
                await _write_system_alert('', '', f'PM Agent 巡检循环崩溃 {runtime_state.loop_crash_count} 次，已停止自动重启')


def get_pm_health() -> dict[str, Any]:
    """获取 PM Agent 健康状态（供 /pm-control/status API 使用）。"""
    task_alive = runtime_state.pm_agent_task is not None and not runtime_state.pm_agent_task.done()
    last_scan_at = runtime_state.last_scan_at
    seconds_since_last_scan = (time.time() - last_scan_at) if last_scan_at > 0 else None

    # 如果超过 2 轮巡检间隔没有扫描，认为循环不健康
    is_healthy = task_alive
    if seconds_since_last_scan is not None and seconds_since_last_scan > SCAN_INTERVAL_SECONDS * 2:
        is_healthy = False

    return {
        'task_alive': task_alive,
        'is_healthy': is_healthy,
        'last_scan_ago_seconds': int(seconds_since_last_scan) if seconds_since_last_scan else None,
        'crash_count': runtime_state.loop_crash_count,
        'last_round_degraded_count': runtime_state.last_round_degraded_count,
        'scan_interval_seconds': SCAN_INTERVAL_SECONDS,
        'consecutive_idle_rounds': runtime_state.consecutive_idle_rounds,
        'idle_throttled': runtime_state.consecutive_idle_rounds >= IDLE_THRESHOLD_ROUNDS,
        'circuit_breakers': _get_circuit_status_safe(),
        'metrics': _get_metrics_safe(),
    }


def _get_circuit_status_safe() -> dict:
    """安全获取熔断器状态（避免循环导入）。"""
    try:
        from app.services.pm.pm_llm_guard import get_circuit_status

        return get_circuit_status()
    except Exception:
        return {}


def _get_metrics_safe() -> dict:
    """安全获取结构化指标（避免循环导入）。"""
    try:
        from app.services.pm.pm_metrics import get_pm_metrics

        return get_pm_metrics().snapshot()
    except Exception:
        return {}


async def _cleanup_old_logs():
    """定期清理过期 PM 日志（GoalStabilityLog 30天 / PMDecisionLog 90天）。

    防止表行数线性增长影响查询性能。
    """
    from datetime import timedelta

    engine = await get_engine('system')
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as _AS

    AsyncSessionLocal = async_sessionmaker(engine, class_=_AS, expire_on_commit=False)
    async with AsyncSessionLocal() as db:
        now = datetime.now()
        # GoalStabilityLog 保留 30 天
        from app.models.goal_stability_log import GoalStabilityLog
        from sqlalchemy import delete as _del

        goal_result = await db.execute(_del(GoalStabilityLog).where(GoalStabilityLog.created_at < now - timedelta(days=30)))
        goal_deleted = goal_result.rowcount

        # PMDecisionLog 保留 90 天（已 resolved 的）
        from app.models.pm_diagnostic_log import PMDiagnosticLog

        diag_result = await db.execute(
            _del(PMDiagnosticLog).where(
                PMDiagnosticLog.resolved.is_(True),
                PMDiagnosticLog.created_at < now - timedelta(days=90),
            )
        )
        diag_deleted = diag_result.rowcount

        # PMDecisionLog 未 resolved 的保留 180 天
        from app.models.pm_decision_log import PMDecisionLog

        dec_result = await db.execute(
            _del(PMDecisionLog).where(
                PMDecisionLog.verified.is_(True),
                PMDecisionLog.created_at < now - timedelta(days=180),
            )
        )
        dec_deleted = dec_result.rowcount

        await db.commit()
        logger.info(f'[PM-Agent] 日志清理完成: GoalStabilityLog -{goal_deleted}, PMDiagnosticLog -{diag_deleted}, PMDecisionLog -{dec_deleted}')


def stop_pm_agent():
    """在应用关闭时停止 PM Agent 后台巡检任务。"""
    if runtime_state.pm_agent_task:
        runtime_state.pm_agent_task.cancel()
        logger.info('[PM-Agent] PM Agent 后台巡检任务已请求停止')


# =============================================================================
# 启动自检：校验注册维度都有修复 handler，防止"注册了但永远 skip"空转
# =============================================================================


def validate_registry():
    """校验 SCAN_REGISTRY 每个维度的 issue_type 都有修复 handler。

    缺失 handler 的维度扫描出来永远走 skip，属于空转配置。
    启动时调用一次，缺失则打 error（不再等到 48h 数据才暴露）。
    """
    from app.services.pm.pm_agent_decision import _has_auto_fix

    missing = []
    for name, meta in SCAN_REGISTRY.items():
        if not _has_auto_fix(meta['issue_type']):
            missing.append(f'{name}({meta["issue_type"]})')
    if missing:
        logger.error(f'[PM-Agent] 注册校验失败，以下维度无修复 handler（将空转）: {missing}')
    else:
        logger.info(f'[PM-Agent] 注册校验通过: {len(SCAN_REGISTRY)} 个维度均有修复 handler')
    return missing


# 不再在模块加载时执行自检（避免循环导入导致 PM 模块起不来）
# 改为 register_pm_agent() 启动时调用
