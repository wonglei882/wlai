"""漫剧设定圣经模型 — AI 外置记忆的核心。

将世界观、角色卡、画风、负面词库、集数摘要全部结构化存储，
解决"每集都忘设定"的问题，为提示词编译器提供一致性约束。

模型清单：
- SettingBible: 设定圣经（项目级世界观）
- CharacterCard: 角色卡（外貌/性格/口癖/音色/参考图）
- ArtStyleCard: 画风卡（风格/色调/线条/光影/种子）
- NegativePromptLibrary: 负面词库（全局/角色/场景）
- ComicEpisode: 集数 + 摘要 + 钩子
"""

import uuid

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.sql import func

from app.models.base import Base


class SettingBible(Base):
    """设定圣经 — 项目级世界观结构化存储。"""

    __tablename__ = 'setting_bibles'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    user_id = Column(String(100), nullable=False, index=True)

    world_name = Column(String(200), nullable=False, comment='世界观名称')
    summary = Column(Text, comment='世界观概述')
    time_period = Column(String(100), comment='时代背景（古代/现代/未来/架空）')
    location_rules = Column(JSON, default=dict, comment='地点规则列表')
    magic_system = Column(JSON, default=dict, comment='力量体系（如有）')
    tone = Column(String(100), comment='整体基调（热血/治愈/暗黑/搞笑）')
    extra = Column(JSON, default=dict, comment='扩展字段')

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<SettingBible(id={self.id}, world={self.world_name})>'


class CharacterCard(Base):
    """角色卡 — AI 外置记忆的核心，保证角色跨镜头一致性。"""

    __tablename__ = 'character_cards'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    bible_id = Column(
        String(36), ForeignKey('setting_bibles.id', ondelete='SET NULL'),
        nullable=True, comment='所属设定圣经',
    )
    user_id = Column(String(100), nullable=False, index=True)

    # 基础信息
    name = Column(String(200), nullable=False, comment='角色姓名')
    age = Column(String(50), comment='年龄（可为范围，如 16-18）')
    gender = Column(String(20), comment='性别')

    # 外貌描述（固定提示词的核心）
    hair = Column(String(200), comment='发型（黑色长发/金色短发/...）')
    eyes = Column(String(100), comment='瞳色（红瞳/蓝瞳/...）')
    outfit = Column(String(500), comment='默认服装描述')
    accessories = Column(JSON, default=list, comment='配饰列表')

    # 性格与行为
    personality = Column(Text, comment='性格描述')
    catchphrase = Column(String(200), comment='口癖/口头禅')
    voice_timbre = Column(String(200), comment='音色描述（用于配音）')

    # AI 出图约束
    appearance_prompt = Column(Text, comment='固定外貌提示词（自动注入所有出图）')
    reference_images = Column(JSON, default=list, comment='参考图 URL 列表')
    negative_traits = Column(JSON, default=list, comment='该角色的负面特征（避免生成的）')

    # 状态：draft → approved → locked
    status = Column(String(20), default='draft', comment='draft/approved/locked')

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<CharacterCard(id={self.id}, name={self.name})>'


class ArtStyleCard(Base):
    """画风卡 — 统一项目视觉风格。"""

    __tablename__ = 'art_style_cards'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    user_id = Column(String(100), nullable=False, index=True)

    style_name = Column(String(100), nullable=False, comment='风格名称（日系赛璐璐/国漫/厚涂/水彩）')
    color_palette = Column(JSON, default=dict, comment='色调配置')
    line_style = Column(String(100), comment='线条风格（细线/粗线/无线条）')
    lighting = Column(String(100), comment='光影风格（柔和/硬光/逆光/体积光）')

    # AI 出图约束
    base_prompt = Column(Text, comment='画风基础提示词（自动注入所有出图）')
    negative_prompt = Column(Text, comment='画风级负面词')
    seed = Column(Integer, comment='固定种子（可选，保证风格一致）')
    reference_images = Column(JSON, default=list, comment='画风参考图')

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<ArtStyleCard(id={self.id}, style={self.style_name})>'


class NegativePromptLibrary(Base):
    """全局负面词库 — 按类别管理禁止出现的元素。"""

    __tablename__ = 'negative_prompt_libraries'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )

    category = Column(
        String(50), nullable=False, default='universal',
        comment='类别: universal/character/scene',
    )
    prompts = Column(JSON, default=list, comment='负面词列表')
    description = Column(String(500), comment='描述')

    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f'<NegativePromptLibrary(id={self.id}, category={self.category})>'


class ComicEpisode(Base):
    """集数 + 摘要 — 每集的结构化记忆。"""

    __tablename__ = 'comic_episodes'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    user_id = Column(String(100), nullable=False, index=True)

    episode_number = Column(Integer, nullable=False, comment='集数')
    title = Column(String(200), comment='集标题')
    summary = Column(Text, comment='本集摘要（上一集发生了什么）')
    next_hook = Column(Text, comment='下一集钩子')
    status = Column(String(20), default='draft', comment='draft/in_progress/completed')

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<ComicEpisode(id={self.id}, ep={self.episode_number})>'
