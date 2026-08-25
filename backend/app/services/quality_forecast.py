"""章节质量预报（独立部署桩实现）。

主系统中基于历史章节质量数据 + AI 预报未来风险；
独立部署下暂不启用预报能力，返回空风险列表，
保证事件总线调用链完整且不产生噪音。
"""
import logging

logger = logging.getLogger(__name__)


async def generate_forecast(db, project_id: str, chapter_id: str) -> list:
    """生成章节质量风险预报（独立部署：返回空列表）。"""
    logger.info(
        '[quality_forecast] 独立部署桩模式，跳过质量预报: project=%s chapter=%s',
        str(project_id)[:8],
        str(chapter_id)[:8],
    )
    return []


def get_risk_summary(risks: list) -> str:
    """将风险列表转为摘要文本。"""
    if not risks:
        return ''
    lines = []
    for risk in risks:
        severity = getattr(risk, 'severity', 'info')
        description = getattr(risk, 'description', str(risk))
        lines.append(f'[{severity}] {description}')
    return '\n'.join(lines)
