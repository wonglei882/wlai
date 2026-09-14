"""PM 漫剧一致性状态快照表 — 按项目×镜头汇聚视觉/场景/镜头/衔接状态"""

import uuid

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.models.base import Base


class PMConsistencyStateComic(Base):
    """漫剧镜头 gate 通过后自动写入的状态快照，供 PM 工具做漫剧一致性检查"""

    __tablename__ = 'pm_consistency_state_comic'

    __table_args__ = (UniqueConstraint('project_id', 'shot_id', name='uq_pm_consistency_comic_project_shot'),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    episode_id = Column(String(36), ForeignKey('comic_episodes.id', ondelete='SET NULL'), nullable=True)
    shot_id = Column(String(36), ForeignKey('comic_shots.id', ondelete='CASCADE'), nullable=False, index=True)
    shot_number = Column(Integer, nullable=False, comment='镜号')

    # 角色视觉状态: {"林风": {"appearance": "黑色长发；红瞳；青色道袍"}, ...}
    character_visual_states = Column(JSON, nullable=False, default=dict, comment='镜头内角色的定稿外貌')

    # 场景状态: {"scene_type": "中景", "visual": "宗门大殿前"}
    scene_state = Column(JSON, nullable=False, default=dict, comment='场景类型/画面描述')

    # 镜头状态: {"camera_movement": "推", "scene_type": "中景"}
    camera_state = Column(JSON, nullable=False, default=dict, comment='镜头运动/景别状态')

    # 前向一致性: {"prev_shot": 3, "sim": 0.82} 与前一镜的衔接
    forward = Column(JSON, nullable=False, default=dict, comment='前向一致性（与前一镜衔接）')

    # 后向一致性评分: 视觉门控的 consistency_score（0-1）
    backward_consistency_score = Column(Float, nullable=True, comment='后向视觉一致性评分')

    # 全局序列: 镜头在分镜表内的序号（跨镜衔接基准）
    global_sequence = Column(Integer, nullable=True, comment='镜头的全局序列号')

    created_at = Column(DateTime, server_default=func.now(), nullable=False, comment='快照创建时间')

    def __repr__(self):
        return f'<PMConsistencyStateComic(proj={self.project_id[:8]}, shot={self.shot_number})>'