#!/usr/bin/env python3
"""PM Agent 主动巡检 runner —— 对所有项目执行主动巡检并按规则写日志。

规则：
  1. 从 projects 表查询该用户的所有项目 ID（附带 user_id）
  2. 对每个项目调用 run_proactive_inspection(db, project_id, user_id)
  3. 若 overall_health_score < 8.0 -> logger.info 记录完整巡检结果
  4. 若存在任何 critical 级别 issue -> logger.warning 记录

用法（在 mumuainovel 容器内执行，因其已配置好 DATABASE_URL 与依赖）：
  docker exec -i mumuainovel python - <<'PYEOF'
  ... 见 cron 调用 ...
  PYEOF
本文件亦可被 cron 直接 pipe 进容器执行，避免 Windows/MSYS 绑定挂载不同步。
"""

import asyncio
import logging
import os
from datetime import datetime

LOG_DIR = '/app/logs'
os.makedirs(LOG_DIR, exist_ok=True)
today = datetime.now().strftime('%Y%m%d')
log_file = os.path.join(LOG_DIR, f'pm_inspection_{today}.log')

logger = logging.getLogger('pm_inspection')
logger.setLevel(logging.INFO)
fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', '%Y-%m-%d %H:%M:%S')
_s = logging.StreamHandler()
_s.setFormatter(fmt)
logger.addHandler(_s)  # noqa: E702
_f = logging.FileHandler(log_file, encoding='utf-8')
_f.setFormatter(fmt)
logger.addHandler(_f)  # noqa: E702

HEALTH_THRESHOLD = 8.0


async def main():
    from sqlalchemy import text
    from app.database import get_db_session
    from app.services.pm.pm_proactive_inspector import run_proactive_inspection

    proj_db = await get_db_session('system')
    async with proj_db:
        result = await proj_db.execute(text('SELECT id, user_id, title FROM projects'))
        rows = result.fetchall()

    if not rows:
        logger.info('无项目，跳过巡检。')
        return

    users = sorted({r[1] for r in rows})
    logger.info(f'共 {len(rows)} 个项目，归属用户: {users}')
    logger.info('开始 PM 主动巡检...')

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

        score = report.get('overall_health_score', 10.0)
        issues = report.get('issues', [])
        warnings = report.get('warnings', [])
        suggestions = report.get('suggestions', [])

        has_critical = any(item.get('severity') == 'critical' for item in (issues + warnings))

        if score < HEALTH_THRESHOLD:
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
    logger.info(f'  低分项目 (score < {HEALTH_THRESHOLD}): {len(low_score)} 个')
    logger.info(f'  含 critical 问题: {len(critical_projects)} 个')
    if low_score:
        logger.info('  低分项目清单:')
        for project_id, uid, score in low_score:
            logger.info(f'    - {project_id[:8]} (user={uid}) score={score:.1f}')
    if not low_score:
        logger.info('所有项目健康，无需要关注的低分项目。')
    logger.info(f'日志已写入: {log_file}')


if __name__ == '__main__':
    asyncio.run(main())
