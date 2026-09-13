"""PM 修复步骤组合编排 — 参照量子算法项目 Circuit.append() 模式。

将复杂修复拆分为可复用的子步骤（FixStep），通过 FixChain 链式组合。
每个 FixStep 是独立的 async 函数，签名统一为:
    async def step(issue, project_id, user_id, db) -> str

使用示例:
    chain = FixChain('world_rule_drift')
    chain.append(hash_align_step)
    chain.append(foreshadow_plant_step)
    chain.append(llm_suggest_step)
    results = await chain.execute(issue, project_id, user_id, db)
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import logging

logger = logging.getLogger(__name__)

# FixStep 类型别名：接收 (issue, project_id, user_id, db) 返回动作描述字符串
FixStep = Callable[[dict[str, Any], str, str, Any], Awaitable[str]]


@dataclass
class FixChain:
    """修复步骤链 — 组合多个子修复步骤，按顺序执行。

    Attributes:
        name: 链名称（通常对应 diag_type 前缀）
        steps: 有序步骤列表
        on_failure: 失败策略 'stop'（遇到错误即停）| 'continue'（跳过失败步骤继续）
    """

    name: str
    steps: list[FixStep] = field(default_factory=list)
    on_failure: str = 'stop'

    def append(self, step: FixStep) -> 'FixChain':
        """链式追加步骤（返回 self 支持链式调用）。"""
        self.steps.append(step)
        return self

    async def execute(
        self,
        issue: dict[str, Any],
        project_id: str,
        user_id: str,
        db: Any,
    ) -> list[str]:
        """按顺序执行所有步骤，返回各步骤结果描述列表。

        on_failure='stop' 时，任一步骤异常即终止并抛出。
        on_failure='continue' 时，异常步骤记录错误日志并跳过。
        """
        results: list[str] = []
        for i, step in enumerate(self.steps):
            step_name = getattr(step, '__name__', f'step_{i}')
            try:
                result = await step(issue, project_id, user_id, db)
                results.append(f'{step_name}: {result}' if result else step_name)
                logger.debug(
                    '[FixChain] %s step %d/%d %s OK',
                    self.name,
                    i + 1,
                    len(self.steps),
                    step_name,
                )
            except Exception as e:
                if self.on_failure == 'stop':
                    logger.error(
                        '[FixChain] %s step %d/%d %s 失败: %s',
                        self.name,
                        i + 1,
                        len(self.steps),
                        step_name,
                        e,
                    )
                    raise
                logger.warning(
                    '[FixChain] %s step %d/%d %s 失败（跳过）: %s',
                    self.name,
                    i + 1,
                    len(self.steps),
                    step_name,
                    e,
                )
                results.append(f'{step_name}: FAILED ({e})')
        return results


# =============================================================================
# 预定义的可复用修复步骤
# =============================================================================


async def hash_align_step(
    issue: dict[str, Any], project_id: str, user_id: str, db: Any
) -> str:
    """世界观规则 hash 对齐步骤 — 将章节 world_states._world_rules_hash 与最新规则对齐。"""
    from app.agent.domain.tools.pm_consistency import handle_pm_auto_fix_world_consistency

    current_ch = issue.get('from_chapter', 0) or 0
    await handle_pm_auto_fix_world_consistency(
        {'project_id': project_id, 'current_chapter': current_ch, 'violations': [issue]},
        db,
    )
    return f'规则 hash 已对齐（第{current_ch}章）'


async def foreshadow_plant_step(
    issue: dict[str, Any], project_id: str, user_id: str, db: Any
) -> str:
    """伏笔补种步骤 — 为漂移的规则变更建立伏笔记录。"""
    from app.models.foreshadow import Foreshadow

    current_ch = issue.get('from_chapter', 0) or 0
    drift_desc = f'世界观规则漂移（第{issue.get("from_chapter")}章→{issue.get("to_chapter")}章）'
    try:
        new_fs = Foreshadow(
            project_id=project_id,
            title=f'[PM] {drift_desc}',
            hint_text=drift_desc,
            status='planted',
            category='event',
            plant_chapter_number=current_ch,
        )
        db.add(new_fs)
        await db.flush()
        return f'伏笔已补种: {drift_desc}'
    except Exception as e:
        return f'伏笔补种失败: {e}'


async def llm_suggest_step(
    issue: dict[str, Any], project_id: str, user_id: str, db: Any
) -> str:
    """LLM 建议生成步骤 — 调用 LLM 分析漂移并生成修改建议。"""
    from app.services.pm.feature_config import is_pm_feature_enabled

    if not is_pm_feature_enabled('optional.world_drift_llm_fix'):
        return 'LLM 建议功能未启用，跳过'

    try:
        from app.services.pm.pm_ai_client import get_pm_ai_client

        ai = await get_pm_ai_client(user_id, db)
        if not ai:
            return 'AIService 获取失败，降级为规则建议'

        current_ch = issue.get('from_chapter', 0) or 0
        prompt = (
            f'分析第{issue.get("from_chapter")}章到第{issue.get("to_chapter")}章的世界观规则漂移，'
            f'给出修改建议。漂移详情: diff_rate={issue.get("diff_rate", "?")}'
        )
        suggestion = await ai.generate(prompt, max_tokens=500)
        return f'LLM 建议: {suggestion[:200]}' if suggestion else 'LLM 未返回建议'
    except Exception as e:
        return f'LLM 建议生成异常: {e}'
