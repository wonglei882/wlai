#!/usr/bin/env python3
"""PM Agent 主动巡检脚本 - 对所有用户的所有项目执行巡检"""

import asyncio
import logging
import sys
import os
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler('logs/pm_inspection.log', encoding='utf-8')],
)
logger = logging.getLogger(__name__)


async def get_all_projects(db):
    """从数据库获取所有项目"""
    from sqlalchemy import select
    from app.models import Project

    result = await db.execute(select(Project.id, Project.user_id, Project.title).order_by(Project.updated_at.desc()))
    projects = result.all()

    return [{'id': p[0], 'user_id': p[1], 'title': p[2]} for p in projects]


async def run_inspection_for_all_projects():
    """对所有项目执行主动巡检"""
    from app.database import get_engine
    from app.services.pm.pm_proactive_inspector import run_proactive_inspection
    from sqlalchemy.ext.asyncio import AsyncSession

    logger.info('=' * 60)
    logger.info('PM Agent 主动巡检开始')
    logger.info(f'巡检时间: {datetime.now().isoformat()}')
    logger.info('=' * 60)

    try:
        # 获取引擎（使用共享PostgreSQL）
        engine = await get_engine('system')

        from sqlalchemy.ext.asyncio import async_sessionmaker

        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with AsyncSessionLocal() as session:
            # 查询所有项目
            projects = await get_all_projects(session)

        if not projects:
            logger.info('未找到任何项目，巡检结束')
            return []

        logger.info(f'共找到 {len(projects)} 个项目，开始逐个巡检...')

        results = []
        low_health_count = 0
        critical_count = 0

        for project in projects:
            project_id = project['id']
            user_id = project['user_id']
            title = project['title']

            logger.info(f'\n{"─" * 50}')
            logger.info(f'巡检项目: {title}')
            logger.info(f'  项目ID: {project_id[:8]}...')
            logger.info(f'  用户ID: {user_id[:8]}...')

            try:
                # 为每个项目创建独立会话
                async with AsyncSessionLocal() as session:
                    report = await run_proactive_inspection(db=session, project_id=project_id, user_id=user_id)

                results.append(report)

                # 检查健康分数
                health_score = report['overall_health_score']
                issues = report.get('issues', [])
                warnings = report.get('warnings', [])

                # 统计 critical 级别 issue
                critical_issues = [i for i in issues if i.get('severity') == 'critical']
                if critical_issues:
                    critical_count += len(critical_issues)
                    logger.warning(
                        f"[CRITICAL] 项目 '{title}' 发现 {len(critical_issues)} 个严重问题:\n"
                        + '\n'.join([f'  - {i.get("title", "N/A")}' for i in critical_issues])
                    )

                # 健康分数 < 8.0 时记录日志
                if health_score < 8.0:
                    low_health_count += 1
                    logger.info(
                        f"[巡检结果] 项目 '{title}':\n"
                        f'  健康分数: {health_score:.1f} (⚠️ 低于阈值8.0)\n'
                        f'  问题数: {len(issues)}\n'
                        f'  警告数: {len(warnings)}\n'
                        f'  建议: {report.get("suggestions", [{}])[0].get("title", "N/A") if report.get("suggestions") else "N/A"}'
                    )

                    # 详细记录 issues
                    for issue in issues:
                        logger.info(f'  [ISSUE] {issue.get("type", "unknown")}: {issue.get("title", "N/A")} - {issue.get("description", "")}')

                    # 详细记录 warnings
                    for warning in warnings:
                        logger.info(f'  [WARNING] {warning.get("type", "unknown")}: {warning.get("title", "N/A")} - {warning.get("description", "")}')
                else:
                    logger.info(f"[巡检结果] 项目 '{title}': 健康分数 {health_score:.1f} ✓")

            except Exception as e:
                logger.error(f"巡检项目 '{title}' 时出错: {str(e)}", exc_info=True)
                results.append(
                    {
                        'project_id': project_id,
                        'user_id': user_id,
                        'title': title,
                        'overall_health_score': 0.0,
                        'error': str(e),
                        'issues': [],
                        'warnings': [],
                    }
                )

        # 汇总统计
        logger.info('\n' + '=' * 60)
        logger.info('PM Agent 主动巡检汇总')
        logger.info('=' * 60)
        logger.info(f'总项目数: {len(projects)}')
        logger.info(f'低健康项目数 (score < 8.0): {low_health_count}')
        logger.info(f'严重问题数: {critical_count}')
        logger.info(f'巡检完成时间: {datetime.now().isoformat()}')

        if low_health_count > 0:
            logger.warning(f'⚠️ 警告: 有 {low_health_count} 个项目需要关注')
        if critical_count > 0:
            logger.warning(f'🚨 严重: 有 {critical_count} 个严重问题需要立即处理')

        return results

    except Exception as e:
        logger.error(f'巡检过程出错: {str(e)}', exc_info=True)
        raise


def main():
    """主入口"""
    asyncio.run(run_inspection_for_all_projects())


if __name__ == '__main__':
    main()
