#!/usr/bin/env python3
"""PM Agent 主动巡检统一入口（合并原 run_pm_inspection / pm_runner / pm_inspector_cron 三脚本）。

用法：
    python pm_inspection_runner.py [--log-dir DIR] [--threshold 8.0]

行为：
    1. 查询全部项目（附带 user_id、title）
    2. 对每个项目调用 run_proactive_inspection(db, project_id, user_id)
    3. overall_health_score < threshold → logger.info 记录完整结果
    4. 存在 critical 级别 issue → logger.warning 记录
    5. 输出汇总统计

参数：
    --log-dir DIR  日志目录（默认 backend/logs；传空字符串 "" 则仅输出控制台）
    --threshold N  健康分阈值（默认 8.0）

历史（2026-08-25）：原三个入口脚本逻辑完全重叠（同一张 projects 表 + 同一巡检
函数 + 同一阈值分级），合并为本统一入口；三个旧文件保留为薄壳转发，兼容外部
cron / docker exec 引用路径不变。
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime

# 添加项目路径（保证直接 python 执行时能 import app）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HEALTH_THRESHOLD = 8.0


def build_logger(name: str = 'pm_inspection', log_dir: str | None = None) -> logging.Logger:
    """构建日志器：控制台 + 可选按天分文件（log_dir 非空时）。"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', '%Y-%m-%d %H:%M:%S')
    _s = logging.StreamHandler()
    _s.setFormatter(fmt)
    logger.addHandler(_s)  # noqa: E702
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        today = datetime.now().strftime('%Y%m%d')
        log_file = os.path.join(log_dir, f'pm_inspection_{today}.log')
        _f = logging.FileHandler(log_file, encoding='utf-8')
        _f.setFormatter(fmt)
        logger.addHandler(_f)  # noqa: E702
    return logger


async def _fetch_projects(db) -> list[tuple]:
    """查询全部项目 (id, user_id, title)。"""
    from sqlalchemy import text

    result = await db.execute(text('SELECT id, user_id, title FROM projects'))
    return result.fetchall()


async def run_inspection(logger: logging.Logger, threshold: float = HEALTH_THRESHOLD) -> list[dict]:
    """对所有项目执行主动巡检。返回每个项目的 report。"""
    from app.database import get_db_session
    from app.services.pm.pm_proactive_inspector import run_proactive_inspection

    proj_db = await get_db_session('system')
    async with proj_db:
        rows = await _fetch_projects(proj_db)

    if not rows:
        logger.info('无项目，跳过巡检。')
        return []

    users = sorted({r[1] for r in rows})
    logger.info(f'共 {len(rows)} 个项目，归属用户: {users}')
    logger.info('开始 PM 主动巡检...')

    reports = []
    low_score = []
    critical_projects = []

    for project_id, user_id, title in rows:
        uid = user_id or 'system'
        pid_short = project_id[:8]
        try:
            db = await get_db_session(uid)
            async with db:
                report = await run_proactive_inspection(db, project_id, uid)
        except Exception as e:
            logger.warning(f'[巡检 ERROR] project={pid_short} user={uid}: {e!r}')
            continue

        reports.append(report)
        score = report.get('overall_health_score', 10.0)
        issues = report.get('issues', [])
        warnings = report.get('warnings', [])
        suggestions = report.get('suggestions', [])

        has_critical = any(item.get('severity') == 'critical' for item in (issues + warnings))

        if score < threshold:
            low_score.append((project_id, uid, score))
            logger.info(
                f'[巡检] project={pid_short} user={uid} title={title!r} '
                f'score={score:.1f} issues={len(issues)} warnings={len(warnings)} suggestions={len(suggestions)}'
            )
            for it in issues:
                logger.info(f'  ISSUE [{it.get("severity")}] {it.get("title")} — {it.get("description", "")}')
            for w in warnings:
                logger.info(f'  WARN  {w.get("title")} — {w.get("description", "")}')
            for s in suggestions:
                logger.info(f'  SUGGEST {s.get("priority")} {s.get("title")} — {s.get("description", "")}')

        if has_critical:
            critical_projects.append((project_id, uid, score))
            logger.warning(f'[CRITICAL] project={pid_short} user={uid} title={title!r} score={score:.1f} — 检测到 CRITICAL 级别问题!')
            for it in issues + warnings:
                if it.get('severity') == 'critical':
                    logger.warning(f'  CRITICAL: {it.get("title")} — {it.get("description", "")} | detail={it.get("detail", "")}')

    logger.info('=' * 64)
    logger.info(f'巡检完成: 共 {len(rows)} 个项目')
    logger.info(f'  低分项目 (score < {threshold}): {len(low_score)} 个')
    logger.info(f'  含 critical 问题: {len(critical_projects)} 个')
    if low_score:
        logger.info('  低分项目清单:')
        for project_id, uid, score in low_score:
            logger.info(f'    - {project_id[:8]} (user={uid}) score={score:.1f}')
    if not low_score:
        logger.info('所有项目健康，无需要关注的低分项目。')

    return reports


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='PM Agent 主动巡检统一入口')
    parser.add_argument('--log-dir', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs'),
                        help='日志目录（传空字符串则仅控制台输出）')
    parser.add_argument('--threshold', type=float, default=HEALTH_THRESHOLD,
                        help=f'健康分阈值（默认 {HEALTH_THRESHOLD}）')
    args = parser.parse_args(argv)

    logger = build_logger('pm_inspection', log_dir=args.log_dir)
    asyncio.run(run_inspection(logger, threshold=args.threshold))


if __name__ == '__main__':
    main()
