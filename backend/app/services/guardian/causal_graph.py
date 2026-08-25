"""章节因果图服务（独立部署桩实现）。

主系统中基于 AI 推理章节间因果/伏笔关系并维护因果图；
独立部署下无因果图谱基础设施，提供安全降级实现：
- infer_from_content  → 返回 0（不写入任何因果边）
- get_impact_warning  → 返回空串
- delete_for_chapter  → 返回 0
"""
import logging

logger = logging.getLogger(__name__)


async def infer_from_content(db, chapter_id: str, project_id: str, content: str, ai_service=None) -> int:
    """推理章节内容的因果链并写入图（独立部署：返回 0）。"""
    logger.info(
        '[causal_graph] 独立部署桩模式，跳过因果推理: project=%s chapter=%s',
        str(project_id)[:8],
        str(chapter_id)[:8],
    )
    return 0


async def get_impact_warning(db, chapter_id: str, project_id: str) -> str:
    """生成章节变更的影响预警（独立部署：返回空串）。"""
    return ''


async def delete_for_chapter(db, chapter_id: str, project_id: str) -> int:
    """删除章节关联的因果边（独立部署：返回 0）。"""
    return 0
