"""PM 巡检流水线 — 5 阶段显式编排。

参照量子算法项目 5 阶段流水线（参数准备 → 构建 → 执行 → 后处理 → 导出），
将 pm_agent.py 中隐式的 scan → diagnose → fix → verify 流程抽象为显式阶段。

阶段定义:
    Stage 1 VALIDATE  — 参数校验 + 前置条件检查
    Stage 2 SCAN      — 巡检扫描（遍历 SCAN_REGISTRY 各维度）
    Stage 3 DIAGNOSE  — 严重性分类 + 优先级排序
    Stage 4 REPAIR    — 修复执行
    Stage 5 VERIFY    — 验证 + 结果导出

使用方式:
    ctx = PipelineContext(project_id=pid, user_id=uid, scan_round=1)
    pipeline = InspectionPipeline(ctx)
    await pipeline.run()
    # 各阶段结果存储在 ctx.stage_results
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import logging

logger = logging.getLogger(__name__)


class PipelineStage(Enum):
    """巡检流水线 5 阶段。"""

    VALIDATE = 'validate'
    SCAN = 'scan'
    DIAGNOSE = 'diagnose'
    REPAIR = 'repair'
    VERIFY = 'verify'


@dataclass
class PipelineContext:
    """流水线上下文 — 贯穿 5 个阶段的数据容器。

    Attributes:
        project_id: 项目 ID
        user_id: 用户 ID
        scan_round: 当前巡检轮次
        issues: 扫描发现的问题列表
        decisions: 决策记录列表
        stage_results: 各阶段输出结果（阶段名 → 结果 dict）
        metrics: 性能指标（如各阶段耗时）
        errors: 阶段执行中捕获的错误
    """

    project_id: str
    user_id: str
    scan_round: int = 0
    issues: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    stage_results: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record_stage(self, stage: PipelineStage, result: Any) -> None:
        """记录阶段结果。"""
        self.stage_results[stage.value] = result

    def add_error(self, stage: PipelineStage, error: str) -> None:
        """记录阶段错误。"""
        self.errors.append(f'{stage.value}: {error}')


class InspectionPipeline:
    """巡检流水线 — 编排 5 阶段执行。

    每个阶段通过 PipelineContext 传递数据，阶段间解耦。
    日志统一输出 [Pipeline] Stage N/5: STAGE_NAME 格式。
    """

    TOTAL_STAGES = 5

    def __init__(self, ctx: PipelineContext):
        self.ctx = ctx

    async def run(self) -> PipelineContext:
        """执行完整流水线。"""
        for stage in PipelineStage:
            stage_num = list(PipelineStage).index(stage) + 1
            logger.info(
                '[Pipeline] Stage %d/%d: %s - project=%s',
                stage_num,
                self.TOTAL_STAGES,
                stage.value.upper(),
                self.ctx.project_id[:8] if self.ctx.project_id else '?',
            )
            try:
                handler = getattr(self, f'_stage_{stage.value}')
                await handler()
            except Exception as e:
                logger.warning(
                    '[Pipeline] Stage %d/%d: %s 异常 - %s',
                    stage_num,
                    self.TOTAL_STAGES,
                    stage.value.upper(),
                    e,
                )
                self.ctx.add_error(stage, str(e))
        return self.ctx

    async def _stage_validate(self) -> None:
        """Stage 1: 参数校验 + 前置条件检查。"""
        if not self.ctx.project_id:
            raise ValueError('project_id 不能为空')
        if not self.ctx.user_id:
            raise ValueError('user_id 不能为空')
        self.ctx.record_stage(PipelineStage.VALIDATE, {'status': 'ok'})

    async def _stage_scan(self) -> None:
        """Stage 2: 巡检扫描 — 由 pm_agent 注入实际扫描逻辑。

        默认实现为空（占位），实际扫描在 pm_agent 中通过
        pipeline._stage_scan = custom_scan 注入。
        """
        self.ctx.record_stage(PipelineStage.SCAN, {'issues_count': len(self.ctx.issues)})

    async def _stage_diagnose(self) -> None:
        """Stage 3: 严重性分类 + 优先级排序。"""
        # 按 severity 排序: critical > warning > info
        severity_order = {'critical': 0, 'warning': 1, 'info': 2}
        self.ctx.issues.sort(
            key=lambda i: severity_order.get(i.get('severity', 'warning'), 1)
        )
        self.ctx.record_stage(
            PipelineStage.DIAGNOSE,
            {'sorted_count': len(self.ctx.issues)},
        )

    async def _stage_repair(self) -> None:
        """Stage 4: 修复执行 — 由 pm_agent 注入实际修复逻辑。"""
        self.ctx.record_stage(PipelineStage.REPAIR, {'decisions_count': len(self.ctx.decisions)})

    async def _stage_verify(self) -> None:
        """Stage 5: 验证 + 结果导出。"""
        self.ctx.record_stage(
            PipelineStage.VERIFY,
            {
                'total_issues': len(self.ctx.issues),
                'total_decisions': len(self.ctx.decisions),
                'errors': self.ctx.errors,
            },
        )
