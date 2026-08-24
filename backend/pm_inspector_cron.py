"""PM Agent 主动巡检 cron 脚本"""

import asyncio
import logging
import os

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('pm_inspector')

# 健康分阈值
HEALTH_WARNING_THRESHOLD = 8.0


async def main():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    # 读取数据库 URL
    db_url = os.getenv('DATABASE_URL', 'postgresql+asyncpg://mumuai:123456@mumuainovel-postgres:5432/mumuai_novel')
    engine = create_async_engine(db_url, echo=False, pool_size=5, max_overflow=10)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            # 1. 查询所有项目
            result = await db.execute(text('SELECT id, user_id, title FROM projects'))
            projects = result.fetchall()

        if not projects:
            logger.info('无项目，跳过巡检')
            return

        logger.info(f'开始 PM 主动巡检，共 {len(projects)} 个项目')

        findings = {'healthy': [], 'warning': [], 'critical': []}

        for proj_row in projects:
            project_id = proj_row[0]
            user_id = proj_row[1]
            project_title = proj_row[2]

            async with session_factory() as db:
                try:
                    from app.services.pm.pm_proactive_inspector import run_proactive_inspection

                    report = await run_proactive_inspection(db, project_id, user_id)
                except Exception as e:
                    logger.warning(f'[PM巡检] 项目 {project_id[:8]} 巡检异常: {e}')
                    continue

            score = report.get('overall_health_score', 10.0)
            issues = report.get('issues', [])
            warnings = report.get('warnings', [])
            suggestions = report.get('suggestions', [])

            # 统计 critical 级别
            has_critical = any(i.get('severity') == 'critical' for i in issues)

            entry = {
                'project_id': project_id,
                'title': project_title,
                'score': score,
                'issues': issues,
                'warnings': warnings,
                'suggestions': suggestions,
            }

            if score < HEALTH_WARNING_THRESHOLD:
                if has_critical:
                    findings['critical'].append(entry)
                else:
                    findings['warning'].append(entry)

                # 步骤3：健康分 < 8.0，将巡检结果记入日志（logger.info）
                logger.info(
                    f'[PM巡检] 项目「{project_title}」({project_id[:8]}) '
                    f'健康分={score:.1f} | issues={len(issues)} warnings={len(warnings)} suggestions={len(suggestions)}'
                )
                for it in issues:
                    logger.info(f'  ISSUE [{it.get("severity")}] {it.get("title")} — {it.get("description", "")}')
                for w in warnings:
                    logger.info(f'  WARN {w.get("title")} — {w.get("description", "")}')
                for s in suggestions:
                    logger.info(f'  SUGGEST {s.get("title")} — {s.get("description", "")}')

                # 步骤4：有 critical 级别 issue，记录 logger.warning
                if has_critical:
                    for it in issues:
                        if it.get('severity') == 'critical':
                            logger.warning(f'[CRITICAL] 项目「{project_title}」({project_id[:8]}): {it.get("title")} — {it.get("description", "")}')
            else:
                findings['healthy'].append(entry)
                logger.info(f'[OK] 项目「{project_title}」({project_id[:8]}) PM健康分={score:.1f}')

        # 汇总
        total = len(projects)
        healthy_n = len(findings['healthy'])
        warn_n = len(findings['warning'])
        crit_n = len(findings['critical'])
        logger.info(f'[PM巡检完成] 共{total}项目 | 健康{healthy_n} | 警告{warn_n} | 严重{crit_n}')

    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
