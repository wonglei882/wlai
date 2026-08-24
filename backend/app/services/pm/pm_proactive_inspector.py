"""PM Agent 主动巡检服务 — 只读健康检查（无副作用）。

职责边界：
- 本模块：只读巡检，检查低质量章节/失败模式/世界观 drift，返回健康分和建议。
  适用于 /inspect API，用户可随时查看项目 PM 状态。
- pm_agent.scan_all_projects()：主动扫描 + 自动修复 + 验证（写操作）。
  适用于 /rerun API 或后台 cron，会修改 PMDecisionLog 等数据。

两者互补：先用本模块查看健康状态，再决定是否触发 scan_all_projects 进行修复。
"""

import logging
from typing import Any
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pm_v2 import FailurePattern
from app.models.pm_consistency_state import PMConsistencyState

logger = logging.getLogger(__name__)

# 质量分数阈值
QUALITY_WARNING_THRESHOLD = 5.0
QUALITY_DANGER_THRESHOLD = 3.0


async def run_proactive_inspection(
    db: AsyncSession,
    project_id: str,
    user_id: str,
) -> dict[str, Any]:
    """执行主动巡检，返回巡检报告。

    检查四个维度：
    1. 低质量章节 — PlotAnalysis 中 overall_quality_score < 5
    2. 高频失败模式 — pm_failure_patterns 中 occurrence_count 排序
    3. 世界观冲突 — PMConsistencyState 中 drift_detected = True
    4. 悬而未决 — 所有 unresolved=True 的决策
    """
    report = {
        'project_id': project_id,
        'user_id': user_id,
        'overall_health_score': 10.0,
        'issues': [],
        'warnings': [],
        'suggestions': [],
    }

    try:
        # 1. 低质量决策
        low_quality = await _check_low_quality_decisions(db, project_id)
        report['issues'].extend(low_quality['issues'])
        report['warnings'].extend(low_quality['warnings'])
        if low_quality['count'] > 0:
            report['overall_health_score'] = min(
                report['overall_health_score'], QUALITY_DANGER_THRESHOLD if low_quality['critical'] > 0 else QUALITY_WARNING_THRESHOLD
            )

        # 2. 高频失败模式
        patterns = await _check_failure_patterns(db, project_id)
        report['warnings'].extend(patterns['warnings'])
        if patterns['high_freq_count'] > 0:
            report['overall_health_score'] = min(report['overall_health_score'], 7.0)

        # 3. 世界观 drift
        drifts = await _check_world_drift(db, project_id)
        report['warnings'].extend(drifts['warnings'])
        if drifts['drift_count'] > 0:
            report['overall_health_score'] = min(report['overall_health_score'], 8.0)

        # 4. 生成建议
        report['suggestions'] = _generate_suggestions(report['issues'], report['warnings'])

        logger.info(
            f'[PM巡检] project={project_id[:8]} score={report["overall_health_score"]:.1f} '
            f'issues={len(report["issues"])} warnings={len(report["warnings"])}'
        )

    except Exception as e:
        logger.warning(f'[PM巡检] 检查失败: {e}')
        report['overall_health_score'] = 5.0
        report['warnings'].append(
            {
                'type': 'inspect_error',
                'severity': 'warning',
                'title': '巡检数据读取异常',
                'description': '无法完整读取项目 PM 数据，建议手动检查。',
            }
        )

    return report


async def _check_low_quality_decisions(
    db: AsyncSession,
    project_id: str,
) -> dict[str, Any]:
    """检查低质量决策

    基于 PlotAnalysis.overall_quality_score（0-10 制），而非不存在的 PMDecisionLog.quality_score。

    注意：只查询数据库中实际存在的字段，避免因模型字段与表结构不同步导致的错误。
    """
    from sqlalchemy import text

    # 只查询已存在的字段，避免因模型新增字段未迁移导致的错误
    sql = text("""
        SELECT id, project_id, chapter_id, plot_stage, overall_quality_score, pacing, analysis_report
        FROM plot_analysis
        WHERE project_id = :project_id
          AND overall_quality_score IS NOT NULL
          AND overall_quality_score < :threshold
        ORDER BY created_at DESC
        LIMIT 10
    """)

    result = await db.execute(sql, {'project_id': project_id, 'threshold': QUALITY_WARNING_THRESHOLD})
    rows = result.fetchall()

    issues = []
    warnings = []
    critical = 0

    for row in rows:
        # row: (id, project_id, chapter_id, plot_stage, overall_quality_score, pacing, analysis_report)
        quality_score = row[4] or 0
        severity = 'critical' if quality_score < QUALITY_DANGER_THRESHOLD else 'warning'
        if severity == 'critical':
            critical += 1

        chapter_id = row[2]
        plot_stage = row[3] or 'N/A'
        pacing = row[5] or 'N/A'
        analysis_report = row[6] or ''

        entry = {
            'type': 'low_quality_chapter',
            'severity': severity,
            'title': f'低质量章节（评分 {quality_score:.1f}）',
            'description': f'章节ID: {chapter_id[:8] if chapter_id else "N/A"} | 剧情: {plot_stage}',
            'detail': (analysis_report[:100] if analysis_report else '') or f'节奏: {pacing}',
            'chapter_id': chapter_id,
        }
        if severity == 'critical':
            issues.append(entry)
        else:
            warnings.append(entry)

    return {'count': len(rows), 'critical': critical, 'issues': issues, 'warnings': warnings}


async def _check_failure_patterns(
    db: AsyncSession,
    project_id: str,
) -> dict[str, Any]:
    """检查高频失败模式"""
    result = await db.execute(
        select(FailurePattern)
        .where(FailurePattern.project_id == project_id)
        .where(FailurePattern.occurrence_count >= 3)
        .order_by(desc(FailurePattern.occurrence_count))
        .limit(5)
    )
    patterns = result.scalars().all()

    warnings = []
    for p in patterns:
        warnings.append(
            {
                'type': 'failure_pattern',
                'severity': 'warning',
                'title': f'重复失败: {p.pattern_type}',
                'description': p.error_description or '',
                'detail': f'已出现 {p.occurrence_count} 次。根因: {p.root_cause or "未记录"}',
                'suggestion': p.recovery_suggestion or '',
            }
        )

    return {'high_freq_count': len(patterns), 'warnings': warnings}


async def _check_world_drift(
    db: AsyncSession,
    project_id: str,
) -> dict[str, Any]:
    """检查世界观 drift"""
    # 查找有 world_states 且包含 drift 标记的一致性状态
    result = await db.execute(
        select(PMConsistencyState).where(PMConsistencyState.project_id == project_id).order_by(desc(PMConsistencyState.chapter_number)).limit(10)
    )
    states = result.scalars().all()

    warnings = []
    drift_count = 0

    for s in states:
        if s.world_states and isinstance(s.world_states, dict) and s.world_states.get('drift_detected'):
            drift_count += 1
            warnings.append(
                {
                    'type': 'world_drift',
                    'severity': 'warning',
                    'title': f'世界观变化（第{s.chapter_number}章）',
                    'description': '世界观设定在相邻章节间发生变化，可能导致逻辑不一致。',
                    'detail': f'章节 {s.chapter_number} 的世界状态与前序章节存在差异。',
                }
            )

    return {'drift_count': drift_count, 'warnings': warnings}


def _generate_suggestions(issues: list, warnings: list) -> list[dict[str, str]]:
    """基于 issues 和 warnings 生成建议"""
    suggestions = []

    # 基于 issue 类型的建议
    issue_types = [i.get('type') for i in issues]
    warning_types = [w.get('type') for w in warnings]

    # 注意：_check_low_quality_decisions 实际 emit 的 type 是 "low_quality_chapter"，
    # 此处曾误写为 "low_quality_decision" 导致该分支永不触发（低质量项目被误判为"健康"）。
    if 'low_quality_chapter' in issue_types:
        suggestions.append(
            {
                'priority': 'high',
                'title': '优先处理低质量章节',
                'description': '点击上方低质量章节，进入对应章节调整 PM 指令或大纲。',
            }
        )

    if 'failure_pattern' in warning_types:
        suggestions.append(
            {
                'priority': 'medium',
                'title': '重复失败模式需系统性修复',
                'description': '建议在 PM Agent 设置中针对性调整对应类型的决策策略。',
            }
        )

    if 'world_drift' in warning_types:
        suggestions.append(
            {
                'priority': 'medium',
                'title': '世界观设定需统一',
                'description': '检查世界观设定，确保各章节间规则一致。',
            }
        )

    if not suggestions:
        suggestions.append(
            {
                'priority': 'low',
                'title': '项目 PM 状态健康',
                'description': '未检测到明显问题，继续保持当前写作节奏。',
            }
        )

    return suggestions
