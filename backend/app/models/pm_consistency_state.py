"""PM 一致性状态快照表 — 按项目×章节汇聚角色/世界观/伏笔/弧线状态"""

from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class PMConsistencyState(Base):
    """每章生成后自动提取的状态快照，供 PM 工具做一致性检查"""

    __tablename__ = 'pm_consistency_state'

    __table_args__ = (UniqueConstraint('project_id', 'chapter_number', name='uq_pm_consistency_project_chapter'),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey('chapters.id', ondelete='SET NULL'), nullable=True)
    chapter_number = Column(Integer, nullable=False, comment='状态所属章节号')

    # 角色状态快照: {"阿铁": {"location":"阴司","emotion":"焦虑","hp":30,"career_stage":"练气初期"}, ...}
    character_states = Column(JSON, nullable=False, default=dict, comment='所有活跃角色的位置/情绪/能力等状态')

    # 世界观进程状态: {"阴阳边界": "消融中","阎王殿": "封锁中", ...}
    world_states = Column(JSON, nullable=False, default=dict, comment='世界观设定中处于变化中的状态')

    # 伏笔状态摘要: {"铜钥匙": "pending", "App弹窗": "planted", ...}
    foreshadow_status = Column(JSON, nullable=False, default=dict, comment='伏笔标题→状态的摘要映射')

    # 角色弧线进度: {"阿铁": "phase2_被动介入", "程野": "phase1_生存挣扎"}
    character_arc_progress = Column(JSON, nullable=False, default=dict, comment='各角色当前所处的弧线阶段')

    # 元信息
    created_at = Column(DateTime, server_default=func.now(), nullable=False, comment='快照创建时间')

    def __repr__(self):
        return f'<PMConsistencyState(proj={self.project_id[:8]}, ch={self.chapter_number})>'
