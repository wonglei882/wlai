"""漫剧数据模型 — 分镜 + 角色视觉参考卡。

服务于漫剧引擎（ComicEngine），提供：
- ComicPanel: 分镜数据存储（场景/角色视觉/对话/镜头）
- VisualReference: 角色视觉参考卡（一致性基准）
"""

import uuid

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.sql import func

from app.models.base import Base


class ComicPanel(Base):
    """漫剧分镜 — 存储单个分镜的完整信息。"""

    __tablename__ = 'comic_panels'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36),
        ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    user_id = Column(String(100), nullable=False, index=True)

    # 分镜定位
    page_number = Column(Integer, nullable=False, comment='页码')
    panel_number = Column(Integer, nullable=False, comment='页内分镜序号')
    global_sequence = Column(Integer, index=True, comment='全局分镜序号（跨页递增）')

    # 场景描述
    scene_description = Column(Text, comment='场景描述（环境/光影/氛围）')
    camera_angle = Column(String(50), comment='镜头角度: close_up/medium/wide/bird_eye')
    transition_type = Column(String(50), comment='转场类型: cut/fade/dissolve/slide')

    # 角色视觉信息
    # [{"name": "主角", "appearance": "黑衣长发", "expression": "愤怒", "action": "拔剑"}]
    characters_visual = Column(JSON, default=list, comment='角色视觉描述列表')

    # 对话信息
    # [{"character": "主角", "text": "我不会放弃！", "bubble_type": "speech/thought/shout"}]
    dialogue = Column(JSON, default=list, comment='对话气泡列表')

    # 场景元数据
    scene_metadata = Column(JSON, default=dict, comment='场景元数据（时间/天气/道具）')

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<ComicPanel(id={self.id}, P{self.page_number}-{self.panel_number})>'


class VisualReference(Base):
    """角色视觉参考卡 — 一致性检测的基准数据。

    存储角色的标准外貌描述、表情变体、服装变体，
    作为 visual_consistency 扫描维度的对比基准。
    """

    __tablename__ = 'visual_references'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36),
        ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    character_name = Column(String(200), nullable=False, comment='角色名称')

    # 标准外貌描述
    canonical_appearance = Column(JSON, default=dict, comment='标准外貌（发型/瞳色/体型/特征）')

    # 变体库
    expression_variants = Column(JSON, default=list, comment='表情变体列表')
    outfit_variants = Column(JSON, default=list, comment='服装变体列表（按场景/篇章区分）')

    # 备注
    notes = Column(Text, comment='视觉设定备注')

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<VisualReference(id={self.id}, character={self.character_name})>'
