"""
PM-Agent ODD（运行设计域）配置

定义 PM-Agent 的运行边界：
- 能处理什么项目
- 能修改什么数据
- 不能做什么操作
- 运行时约束条件
"""

# PM-Agent 运行设计域定义
PM_AGENT_ODD = {
    # 项目域约束
    'domains': {
        'allowed_project_types': ['novel_project'],  # 仅小说项目
        'min_chapter_count': 3,  # 项目至少 3 章才巡检
        'max_chapter_count': 2000,  # 单项目最多 2000 章
        'excluded_project_ids': [],  # 排除的项目 ID（可运行时动态添加）
    },
    # 巡检维度约束
    'dimensions': {
        'enabled': ['character_consistency', 'foreshadow_age', 'world_rule_drift'],
        # 已禁用维度：outline_drift 无实际修复路径（仅写诊断日志），
        # unresolved_diagnostics 无修复 handler，扫描出来均空转
        'disabled': ['outline_drift', 'unresolved_diagnostics'],
    },
    # 修复范围约束
    'repair_scope': {
        'can_modify': [
            'foreshadows',  # 伏笔状态
            'pm_consistency_state',  # 一致性状态
            'pm_decision_log',  # 决策日志
            'pm_diagnostic_logs',  # 诊断日志
            'pm_failure_patterns',  # 失败模式（L5 反思闭环：决策失败根因回写）
        ],
        'can_read': [
            'chapters',  # 章节内容（仅读，LLM 建议不直接改）
            'characters',  # 角色设定
            'projects',  # 项目信息
            'outlines',  # 大纲
            'character_state_history',  # 角色状态历史
        ],
        'cannot_modify': [
            'chapters.content',  # 章节正文（LLM 建议不直接改）
            'projects.world_rules',  # 世界观规则（只能对齐 hash）
            'characters.core_attributes',  # 角色核心属性
        ],
    },
    # 运行时约束
    'runtime': {
        'max_issues_per_round': 100,  # 单轮最多处理 100 问题
        'max_retries_per_issue': 3,  # 单问题最多重试 3 次
        'cooldown_hours': {
            'environment_failure': 1 / 6,  # 环境类失败：10 分钟
            'logic_failure': 24,  # 逻辑类失败：24 小时
        },
    },
    # 时间窗口约束
    'time_windows': {
        'enabled': False,  # 当前 24h 运行，无限制
        'timezone': 'Asia/Shanghai',
        'active_hours': [(0, 24)],  # 0-24 点均可运行
    },
    # 性能约束
    'performance': {
        'max_round_duration_seconds': 300,  # 单轮最多 5 分钟
        'max_llm_tokens_per_issue': 600,  # 单问题 LLM 最多 600 tokens
        'max_concurrent_projects': 10,  # 最多并行 10 项目
    },
    # 降级策略
    'degradation': {
        'when_odd_violated': 'readonly',  # ODD 外自动降级为只读模式
        'when_overloaded': 'skip_round',  # 超载时跳过本轮
        'when_kill_switch_triggered': 'immediate_stop',  # Kill Switch 触发立即停止
    },
}


def check_odd_boundary(project: dict, issues: list = None) -> dict:
    """
    检查当前操作是否在 ODD 内

    Args:
        project: 项目信息（含 id, type, chapter_count 等）
        issues: 问题列表（可选，用于检查数量约束）

    Returns:
        {
            "in_odd": bool,  # 是否在 ODD 内
            "violations": List[str],  # 违规项列表
            "degraded_mode": Optional[str]  # 降级模式（None / "readonly" / "skip_round"）
        }
    """
    violations = []
    odd = PM_AGENT_ODD

    # 检查 1：项目类型
    project_type = project.get('type', 'novel_project')
    if project_type not in odd['domains']['allowed_project_types']:
        violations.append(f'项目类型 {project_type} 不在 ODD 允许范围内')

    # 检查 2：章节数量
    chapter_count = project.get('chapter_count', 0)
    min_chapters = odd['domains']['min_chapter_count']
    max_chapters = odd['domains']['max_chapter_count']

    if chapter_count < min_chapters:
        violations.append(f'章节数量 {chapter_count} < 最低要求 {min_chapters}')

    if chapter_count > max_chapters:
        violations.append(f'章节数量 {chapter_count} > 上限 {max_chapters}')

    # 检查 3：项目排除列表
    project_id = project.get('id', '')
    if project_id in odd['domains']['excluded_project_ids']:
        violations.append(f'项目 {project_id} 在排除列表中')

    # 检查 4：问题数量（如果提供了 issues）
    if issues is not None:
        max_issues = odd['runtime']['max_issues_per_round']
        if len(issues) > max_issues:
            violations.append(f'问题数量 {len(issues)} > 上限 {max_issues}')

    # 决定是否在 ODD 内
    in_odd = len(violations) == 0

    # 决定降级模式
    degraded_mode = None
    if not in_odd:
        # 章节过少 → 跳过本轮；其他违规 → 只读模式
        degraded_mode = 'skip_round' if chapter_count < min_chapters else odd['degradation']['when_odd_violated']

    return {'in_odd': in_odd, 'violations': violations, 'degraded_mode': degraded_mode}


def get_allowed_modifications() -> list:
    """获取 PM-Agent 允许修改的表/字段列表"""
    return PM_AGENT_ODD['repair_scope']['can_modify']


def get_forbidden_modifications() -> list:
    """获取 PM-Agent 禁止修改的表/字段列表"""
    return PM_AGENT_ODD['repair_scope']['cannot_modify']


def is_modification_allowed(table: str, field: str = None) -> bool:
    """
    检查是否允许修改指定表/字段

    Args:
        table: 表名
        field: 字段名（可选）

    Returns:
        True 允许修改，False 禁止修改
    """
    odd = PM_AGENT_ODD

    # 检查是否在禁止列表
    for forbidden in odd['repair_scope']['cannot_modify']:
        if '.' in forbidden:
            forbidden_table, forbidden_field = forbidden.split('.', 1)
            if table == forbidden_table and (field is None or field == forbidden_field):
                return False
        else:
            if table == forbidden:
                return False

    # 检查是否在允许列表
    allowed = odd['repair_scope']['can_modify']

    # 默认禁止
    return table in allowed
