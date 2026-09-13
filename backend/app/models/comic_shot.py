"""漫剧分镜与镜头模型 — 生产流水线的核心。

- Storyboard: 分镜表（一集对应一个分镜表）
- Shot: 镜头（最小生产单位，7 状态流转）
- ShotAsset: 镜头素材（图/视频/配音/字幕/BGM，多版本管理）
"""

import uuid

from sqlalchemy import Column, String, Text, Integer, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.sql import func

from app.models.base import Base


class Storyboard(Base):
    """分镜表 — 一集对应一个分镜表，由小说/故事文本生成。"""

    __tablename__ = 'comic_storyboards'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    episode_id = Column(
        String(36), ForeignKey('comic_episodes.id', ondelete='SET NULL'),
        nullable=True, comment='所属集数',
    )
    user_id = Column(String(100), nullable=False, index=True)

    title = Column(String(200), comment='分镜表标题')
    source_text = Column(Text, comment='原始小说/故事文本')
    shot_count = Column(Integer, default=0, comment='总镜头数')
    status = Column(String(20), default='draft', comment='draft/confirmed')

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<Storyboard(id={self.id}, shots={self.shot_count})>'


class Shot(Base):
    """镜头 — 最小生产单位（7 状态流转）。

    状态机：
        pending_script → pending_image → pending_review_image
        → pending_video → pending_voice → pending_composite → completed
    """

    __tablename__ = 'comic_shots'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    storyboard_id = Column(
        String(36), ForeignKey('comic_storyboards.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    episode_id = Column(
        String(36), ForeignKey('comic_episodes.id', ondelete='SET NULL'),
        nullable=True,
    )
    user_id = Column(String(100), nullable=False, index=True)

    # 镜头描述
    shot_number = Column(Integer, nullable=False, comment='镜号')
    duration = Column(Float, default=4.0, comment='时长（秒，3-5）')
    scene_type = Column(String(50), comment='景别: 特写/近景/中景/全景/远景')
    visual_description = Column(Text, comment='画面描述')
    character_action = Column(Text, comment='角色动作')
    dialogue = Column(String(100), comment='台词（<=15字）')
    sound_effect = Column(String(200), comment='音效')
    camera_movement = Column(String(100), comment='镜头运动: 推/拉/摇/移/固定')

    # 生产状态
    status = Column(String(30), default='pending_script', comment='镜头状态（7 状态流转）')
    compiled_prompt = Column(Text, comment='编译后的提示词')
    negative_prompt = Column(Text, comment='编译后的负面词')
    seed = Column(Integer, comment='使用的种子')
    retry_count = Column(Integer, default=0, comment='重试次数')
    corrected_prompt = Column(Text, nullable=True, comment='修正后的提示词（视觉重试时注入）')
    last_consistency_score = Column(Float, nullable=True, comment='最近一次视觉一致性评分')
    metadata_json = Column(JSON, default=dict, comment='扩展元数据（匹配角色/钩子标记等）')

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<Shot(id={self.id}, #{self.shot_number}, status={self.status})>'


class ShotAsset(Base):
    """镜头素材 — 每个镜头可有多版本素材。

    命名规范：项目_集数_镜号_版本
    """

    __tablename__ = 'comic_shot_assets'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shot_id = Column(
        String(36), ForeignKey('comic_shots.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    project_id = Column(
        String(36), ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    user_id = Column(String(100), nullable=False, index=True)

    asset_type = Column(String(20), nullable=False, comment='image/video/voice/subtitle/bgm')
    version = Column(Integer, default=1, comment='版本号')
    file_url = Column(String(2000), comment='文件路径/URL')
    prompt_used = Column(Text, comment='生成该素材使用的提示词')
    parameters = Column(JSON, default=dict, comment='参数（种子/模型/参考图等）')
    status = Column(String(20), default='generating', comment='generating/passed/failed/rejected')
    qc_result = Column(JSON, default=dict, comment='质检结果')
    naming = Column(String(500), comment='规范命名：项目_集数_镜号_版本')

    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f'<ShotAsset(id={self.id}, type={self.asset_type}, v{self.version})>'
