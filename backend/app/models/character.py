"""角色数据模型"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean, Integer, Float, Index
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class Character(Base):
    """角色表（包括角色和组织）"""

    __tablename__ = 'characters'

    __table_args__ = (
        Index('idx_character_project', 'project_id'),
        Index('idx_character_role', 'project_id', 'role_type'),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)

    # 基本信息
    name = Column(String(100), nullable=False, comment='角色/组织名称')
    age = Column(String(50), comment='年龄')
    gender = Column(String(50), comment='性别')
    is_organization = Column(Boolean, default=False, comment='是否为组织')

    # 角色类型：protagonist(主角)/supporting(配角)/antagonist(反派)
    role_type = Column(String(50), comment='角色类型')

    # 角色详细信息
    personality = Column(Text, comment='性格特点/组织特性')
    speaking_style = Column(Text, comment='说话风格/语气特点')
    speech_patterns = Column(Text, comment='说话模式：语气词、口头禅、断句特点等结构化描述')
    background = Column(Text, comment='背景故事')
    appearance = Column(Text, comment='外貌描述')
    relationships = Column(Text, comment='人物关系(JSON)')

    # 组织特有字段
    organization_type = Column(String(100), comment='组织类型')
    organization_purpose = Column(String(500), comment='组织目的')
    organization_members = Column(Text, comment='组织成员(JSON)')

    # 角色/组织存活状态
    status = Column(String(20), default='active', comment='状态：active/deceased/missing/retired/destroyed')
    status_changed_chapter = Column(Integer, comment='状态变更的章节号')

    # 心理状态追踪（由章节分析自动更新）
    current_state = Column(Text, comment='角色当前心理状态（由分析自动更新）')
    state_updated_chapter = Column(Integer, comment='心理状态最后更新的章节号')

    # 职业相关字段（冗余字段，用于提升查询性能）
    # 注意：历史版本曾外键引用 careers.id，careers 表未随独立项目交付，故仅保留普通列。
    main_career_id = Column(String(36), comment='主职业ID')
    main_career_stage = Column(Integer, comment='主职业当前阶段')
    sub_careers = Column(Text, comment='副职业列表(JSON): [{"career_id": "xxx", "stage": 3}, ...]')
    screen_time_weight = Column(Float, default=1.0, comment='戏份权重(0.0~1.0)')

    # 其他
    avatar_url = Column(String(500), comment='头像URL')
    traits = Column(Text, comment='特征标签(JSON)')

    created_at = Column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间')

    def __repr__(self):
        entity_type = '组织' if self.is_organization else '角色'
        return f'<Character(id={self.id}, name={self.name}, type={entity_type})>'
