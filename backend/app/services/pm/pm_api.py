"""PM Agent 公共 API 门面（对外唯一入口）。

外部调用方（API 路由 / 入口脚本 / 测试）统一从本模块导入，不直接触碰
pm_agent / pm_agent_decision 内部符号，形成明确的公共边界：

    from app.services.pm.pm_api import (
        scan_all_projects,      # 全量巡检（手动触发 / 定时入口）
        diagnose_and_fix,       # 单项目诊断+修复（在线触发）
        register_pm_agent,      # 应用启动：注册后台巡检任务
        stop_pm_agent,          # 应用关闭：停止后台巡检任务
        get_pm_health,          # 健康状态（/pm-control/status）
        register_pm_handlers,   # 修复 handler 注册（幂等）
    )

与历史兼容再导出的区别：门面是"定义的唯一归属处"——源实现仍在各自模块，
本层只做稳定转发，避免内部拆分导致外部 import 路径频繁漂移。
"""
from app.services.pm.pm_agent import (
    get_pm_health,
    register_pm_agent,
    scan_all_projects,
    stop_pm_agent,
)
from app.services.pm.pm_agent_decision import diagnose_and_fix
from app.services.pm.pm_fix_handlers import register_pm_handlers

__all__ = [
    'scan_all_projects',
    'diagnose_and_fix',
    'register_pm_agent',
    'stop_pm_agent',
    'get_pm_health',
    'register_pm_handlers',
]
