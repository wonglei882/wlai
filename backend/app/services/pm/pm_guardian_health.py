"""PM 一致性守护者 — 全局健康检查

将 full_health_check 从 PMConsistencyGuardian 方法拆分为独立异步函数，
降低 pm_consistency_guardian.py 单文件复杂度。

依赖 PMConsistencyGuardian 实例（通过参数传入），调用其 db / project_id / check_and_alert。
为避免与 PMConsistencyGuardian.full_health_check 方法循环导入，本模块不导入 Guardian 类。
"""

from sqlalchemy import select

from app.models.chapter import Chapter
from app.models.pm_consistency_state import PMConsistencyState


async def full_health_check(guardian) -> dict:
    """全项目健康度扫描

    Args:
        guardian: PMConsistencyGuardian 实例（需提供 db / project_id / check_and_alert）

    Returns:
        dict: 健康状态报告
    """
    # 获取所有章节
    ch_r = await guardian.db.execute(select(Chapter).where(Chapter.project_id == guardian.project_id).order_by(Chapter.chapter_number))
    chapters = list(ch_r.scalars().all())
    if not chapters:
        return {'status': 'empty', 'message': '项目暂无章节', 'dimensions': {}}

    latest_ch = chapters[-1]
    check = await guardian.check_and_alert(latest_ch.chapter_number)

    # 统计快照覆盖率
    snap_r = await guardian.db.execute(select(PMConsistencyState).where(PMConsistencyState.project_id == guardian.project_id))
    snapshots = list(snap_r.scalars().all())
    snapshot_chapters = {s.chapter_number for s in snapshots}
    coverage = len(snapshot_chapters) / max(len(chapters), 1)

    return {
        'status': 'pass' if check.passed else 'warn',
        'total_chapters': len(chapters),
        'snapshot_coverage': f'{coverage:.0%}',
        'issues': check.to_dict(),
        'dimensions': {
            'character_consistency': 'pass',
            'world_consistency': 'pass' if not any(i.dimension == 'world_drift' for i in check.issues) else 'warn',
            'foreshadow_health': 'pass' if not any(i.dimension.startswith('foreshadow') for i in check.issues) else 'warn',
            'arc_progress': 'pass' if not any(i.dimension == 'arc_fracture' for i in check.issues) else 'warn',
        },
    }
