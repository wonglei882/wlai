"""大纲结构化数据模型 - 借鉴 VolumeGenerationScope 四层设计"""

from __future__ import annotations
from pydantic import BaseModel


# ===== 第4层：拆章 (Chapter Detail) =====
class ChapterPlan(BaseModel):
    """单章规划"""

    title: str
    summary: str = ''
    purpose: str | None = None  # 本章在卷中的功能
    conflict_level: int | None = None  # 冲突强度 1-5
    target_words: int | None = None  # 目标字数
    key_scenes: list[str] = []  # 关键场景列表
    payoff_refs: list[str] = []  # 兑现的伏笔引用


# ===== 第3层：节奏 (Beat Sheet) =====
class VolumeBeat(BaseModel):
    """卷节拍"""

    key: str  # 唯一标识
    label: str  # 节拍名称（如"第一幕铺垫"）
    summary: str  # 节拍内容概要
    chapter_span: str  # 覆盖章节范围（如"1-3"）
    must_deliver: list[str] = []  # 必须达成的剧情目标


class BeatSheet(BaseModel):
    """卷节奏表"""

    volume_id: str
    volume_order: int
    beats: list[VolumeBeat] = []


# ===== 第2层：骨架 (Skeleton) =====
class VolumeSkeletonChapter(BaseModel):
    """骨架中的章节摘要"""

    chapter_order: int
    title: str
    summary: str = ''
    purpose: str | None = None


class VolumeSkeleton(BaseModel):
    """卷骨架"""

    volume_order: int
    volume_title: str
    chapters: list[VolumeSkeletonChapter] = []


# ===== 第1层：战略 (Strategy) =====
class VolumeStrategyItem(BaseModel):
    """单卷战略"""

    sort_order: int
    title: str
    role_label: str  # 卷的角色（如"奠基""高潮""收束"）
    core_reward: str  # 核心爽点/价值
    escalation_focus: str  # 升级重点


class StrategyPlan(BaseModel):
    """卷战略规划"""

    volume_count: int
    reader_reward_ladder: str  # 读者奖励阶梯
    escalation_ladder: str  # 冲突升级阶梯
    midpoint_shift: str  # 中点转折方向
    volumes: list[VolumeStrategyItem] = []


# ===== 顶层结构 =====
class OutlineStructure(BaseModel):
    """
    大纲结构化数据 - 四层设计

    用法:
      outline.structure = OutlineStructure(
          strategy=StrategyPlan(...),
          volumes=[VolumeSkeleton(...)],
          beat_sheets=[BeatSheet(...)],
      ).model_dump_json()
    """

    version: str = 'v1'
    strategy: StrategyPlan | None = None  # 战略层
    volumes: list[VolumeSkeleton] = []  # 骨架层（含拆章）
    beat_sheets: list[BeatSheet] = []  # 节奏层

    def has_data(self) -> bool:
        """是否有结构化数据"""
        return bool(self.strategy) or bool(self.volumes) or bool(self.beat_sheets)
