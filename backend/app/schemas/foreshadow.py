"""伏笔管理 Pydantic Schema"""

from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from enum import Enum


class ForeshadowStatus(str, Enum):  # noqa: UP042
    """伏笔状态枚举"""

    PENDING = 'pending'  # 待埋入
    PLANTED = 'planted'  # 已埋入
    RESOLVED = 'resolved'  # 已回收
    PARTIALLY_RESOLVED = 'partially_resolved'  # 部分回收
    ABANDONED = 'abandoned'  # 已废弃
    ACTIVE = 'active'  # 生效中（已埋入且未回收、未老化）
    STALE = 'stale'  # 已老化（待 PM 处理）


class ForeshadowSourceType(str, Enum):  # noqa: UP042
    """伏笔来源类型"""

    ANALYSIS = 'analysis'  # 分析提取
    MANUAL = 'manual'  # 手动添加


class ForeshadowCategory(str, Enum):  # noqa: UP042
    """伏笔分类"""

    IDENTITY = 'identity'  # 身世
    MYSTERY = 'mystery'  # 悬念
    ITEM = 'item'  # 物品
    RELATIONSHIP = 'relationship'  # 关系
    EVENT = 'event'  # 事件
    ABILITY = 'ability'  # 能力
    PROPHECY = 'prophecy'  # 预言


class ForeshadowBase(BaseModel):
    """伏笔基础信息"""

    title: str = Field(..., min_length=1, max_length=200, description='伏笔标题')
    content: str = Field(..., min_length=1, description='伏笔详细内容/描述')
    hint_text: str | None = Field(None, description='埋伏笔时的暗示文本')
    resolution_text: str | None = Field(None, description='回收伏笔时的揭示文本')

    # 章节关联
    plant_chapter_number: int | None = Field(None, ge=1, description='计划埋入章节号')
    target_resolve_chapter_number: int | None = Field(None, ge=1, description='计划回收章节号')

    # 状态
    is_long_term: bool = Field(False, description='是否长线伏笔')

    # 重要性
    importance: float = Field(0.5, ge=0.0, le=1.0, description='重要性评分 0.0-1.0')
    strength: int = Field(5, ge=1, le=10, description='伏笔强度 1-10')
    subtlety: int = Field(5, ge=1, le=10, description='隐藏度 1-10')

    # 关联信息
    related_characters: list[str] | None = Field(None, description='关联角色名列表')
    tags: list[str] | None = Field(None, description='标签列表')
    category: str | None = Field(None, description='分类')

    # 备注
    notes: str | None = Field(None, description='创作备注')
    resolution_notes: str | None = Field(None, description='回收方式说明')

    # AI辅助设置
    auto_remind: bool = Field(True, description='是否自动提醒')
    remind_before_chapters: int = Field(5, ge=1, le=20, description='提前几章提醒')
    include_in_context: bool = Field(True, description='是否包含在生成上下文中')


class ForeshadowCreate(ForeshadowBase):
    """创建伏笔请求"""

    project_id: str = Field(..., description='项目ID')


class ForeshadowUpdate(BaseModel):
    """更新伏笔请求"""

    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = Field(None, min_length=1)
    hint_text: str | None = None
    resolution_text: str | None = None

    plant_chapter_number: int | None = Field(None, ge=1)
    target_resolve_chapter_number: int | None = Field(None, ge=1)

    status: ForeshadowStatus | None = None
    is_long_term: bool | None = None

    importance: float | None = Field(None, ge=0.0, le=1.0)
    strength: int | None = Field(None, ge=1, le=10)
    subtlety: int | None = Field(None, ge=1, le=10)
    urgency: int | None = Field(None, ge=0, le=3)

    related_characters: list[str] | None = None
    related_foreshadow_ids: list[str] | None = None
    tags: list[str] | None = None
    category: str | None = None

    notes: str | None = None
    resolution_notes: str | None = None

    auto_remind: bool | None = None
    remind_before_chapters: int | None = Field(None, ge=1, le=20)
    include_in_context: bool | None = None


class ForeshadowResponse(ForeshadowBase):
    """伏笔响应"""

    id: str
    project_id: str

    source_type: str | None = None
    source_memory_id: str | None = None
    source_analysis_id: str | None = None

    plant_chapter_id: str | None = None
    target_resolve_chapter_id: str | None = None
    actual_resolve_chapter_id: str | None = None
    actual_resolve_chapter_number: int | None = None

    status: str = 'pending'
    urgency: int = 0

    related_foreshadow_ids: list[str] | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None
    planted_at: datetime | None = None
    resolved_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ForeshadowListResponse(BaseModel):
    """伏笔列表响应"""

    total: int
    items: list[ForeshadowResponse]
    stats: dict | None = None


class ForeshadowStatsResponse(BaseModel):
    """伏笔统计响应"""

    total: int
    pending: int
    planted: int
    resolved: int
    partially_resolved: int
    abandoned: int
    long_term_count: int
    overdue_count: int  # 超期未回收数量


class PlantForeshadowRequest(BaseModel):
    """标记伏笔埋入请求"""

    chapter_id: str = Field(..., description='埋入章节ID')
    chapter_number: int = Field(..., ge=1, description='埋入章节号')
    hint_text: str | None = Field(None, description='暗示文本')


class ResolveForeshadowRequest(BaseModel):
    """标记伏笔回收请求"""

    chapter_id: str = Field(..., description='回收章节ID')
    chapter_number: int = Field(..., ge=1, description='回收章节号')
    resolution_text: str | None = Field(None, description='揭示文本')
    is_partial: bool = Field(False, description='是否部分回收')


class SyncFromAnalysisRequest(BaseModel):
    """从分析同步伏笔请求"""

    chapter_ids: list[str] | None = Field(None, description='指定章节ID列表，为空则同步全部')
    overwrite_existing: bool = Field(False, description='是否覆盖已存在的伏笔')
    auto_set_planted: bool = Field(True, description='自动设置为已埋入状态')


class SyncFromAnalysisResponse(BaseModel):
    """从分析同步伏笔响应"""

    synced_count: int
    skipped_count: int
    resolved_count: int = 0
    new_foreshadows: list[ForeshadowResponse] = []
    skipped_reasons: list[dict] = []


class ForeshadowContextRequest(BaseModel):
    """获取章节伏笔上下文请求"""

    chapter_number: int = Field(..., ge=1, description='章节号')
    include_pending: bool = Field(True, description='包含待埋入伏笔')
    include_overdue: bool = Field(True, description='包含超期伏笔')
    lookahead: int = Field(5, ge=1, le=20, description='向前看几章')


class ForeshadowContextResponse(BaseModel):
    """伏笔上下文响应"""

    chapter_number: int
    context_text: str
    pending_plant: list[ForeshadowResponse]  # 本章待埋入
    pending_resolve: list[ForeshadowResponse]  # 即将需要回收
    overdue: list[ForeshadowResponse]  # 超期未回收
    recently_planted: list[ForeshadowResponse]  # 最近埋入（可铺垫）
