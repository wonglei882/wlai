"""PM 领域知识包加载器 — 按题材/画风动态加载知识包内容。

目录结构（data/knowledge_packs/）:
- story_themes/<theme_id>/      题材包（README.md / narrative_techniques.md /
                                 red_lines.yaml / fix_strategies.yaml）
- art_styles/<style_id>/        画风包（README.md，供漫剧提示词编译参考）
- agent_skills/<skill>.md       技能卡（决策/巡检/修复/监督，供 Agent 上下文注入）

设计要点（参考 ToonFlow 技能知识包架构）:
- 统一入口 KnowledgePackLoader：题材→包映射复用 RedLineEngine（单一事实来源）
- 修复策略 / 叙事手法 / 技能卡均以 Markdown/YAML 形式外置，可热更新无需改代码
- 加载失败降级：缺文件返回空内容，绝不抛异常（巡检主流程不受影响）
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# knowledge_packs 根目录（backend/data/knowledge_packs）
# 本文件位于 backend/app/services/pm/knowledge_pack.py，上溯 4 级到 backend/
_PACKS_ROOT = Path(__file__).parent.parent.parent.parent / 'data' / 'knowledge_packs'

# 题材包必备文件（缺失时目录仍可发现，但能力降级）
_THEME_FILES = ('README.md', 'narrative_techniques.md', 'red_lines.yaml', 'fix_strategies.yaml')
# 画风包必备文件
_STYLE_FILES = ('README.md',)


@dataclass
class KnowledgePack:
    """单个题材/画风知识包的聚合视图。

    Attributes:
        pack_id: 包 ID（目录名，如 'xianxia_fantasy'）
        pack_type: 包类型（'story_theme' / 'art_style'）
        readme: README.md 全文（Markdown）
        narrative_techniques: 叙事手法全文（题材包专用，可为空）
        red_lines: 题材红线规则列表（由 RedLineEngine 同源加载，可为空）
        fix_strategies: 修复策略列表（YAML fix_strategies 段，可为空）
    """

    pack_id: str = ''
    pack_type: str = 'story_theme'
    readme: str = ''
    narrative_techniques: str = ''
    red_lines: list[dict[str, Any]] = field(default_factory=list)
    fix_strategies: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（供前端 / 提示词组装使用）。"""
        return {
            'pack_id': self.pack_id,
            'pack_type': self.pack_type,
            'readme': self.readme[:2000],
            'has_narrative_techniques': bool(self.narrative_techniques),
            'red_line_count': len(self.red_lines),
            'fix_strategy_count': len(self.fix_strategies),
        }


class KnowledgePackLoader:
    """知识包加载器 — 发现、缓存、按需聚合题材/画风包内容。

    单例语义：模块级实例 knowledge_pack_loader 全局复用（与 RedLineEngine 一致）。
    """

    def __init__(self) -> None:
        self._theme_packs: dict[str, KnowledgePack] = {}
        self._style_packs: dict[str, KnowledgePack] = {}
        self._discovered = False
        self._genre_map_cache: dict[str, str] = {}  # genre → theme_id

    # ------------------------------------------------------------------
    # 发现与缓存
    # ------------------------------------------------------------------

    def _discover(self) -> None:
        """扫描目录，发现全部题材包与画风包（懒加载缓存）。"""
        if self._discovered:
            return
        try:
            theme_root = _PACKS_ROOT / 'story_themes'
            if theme_root.exists():
                for d in theme_root.iterdir():
                    if d.is_dir() and not d.name.startswith('.'):
                        self._theme_packs[d.name] = self._load_theme_pack(d)
            style_root = _PACKS_ROOT / 'art_styles'
            if style_root.exists():
                for d in style_root.iterdir():
                    if d.is_dir() and not d.name.startswith('.'):
                        self._style_packs[d.name] = self._load_style_pack(d)
        except Exception as e:
            logger.warning(f'[知识包] 知识包目录扫描失败: {e}')
        self._discovered = True

    def _load_theme_pack(self, d: Path) -> KnowledgePack:
        """加载单个题材包目录内容（缺文件降级为空，不抛异常）。"""
        pack = KnowledgePack(pack_id=d.name, pack_type='story_theme')
        try:
            readme_path = d / 'README.md'
            pack.readme = readme_path.read_text(encoding='utf-8') if readme_path.exists() else ''
        except Exception as e:
            logger.warning(f'[知识包] 读取 README 失败 {d.name}: {e}')
        try:
            tech_path = d / 'narrative_techniques.md'
            if tech_path.exists():
                pack.narrative_techniques = tech_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning(f'[知识包] 读取叙事手法失败 {d.name}: {e}')
        # 红线与修复策略走 YAML 解析
        pack.red_lines = self._load_yaml_list(d / 'red_lines.yaml', 'red_lines')
        pack.fix_strategies = self._load_yaml_list(d / 'fix_strategies.yaml', 'fix_strategies')
        return pack

    def _load_style_pack(self, d: Path) -> KnowledgePack:
        """加载单个画风包目录内容。"""
        pack = KnowledgePack(pack_id=d.name, pack_type='art_style')
        try:
            readme_path = d / 'README.md'
            pack.readme = readme_path.read_text(encoding='utf-8') if readme_path.exists() else ''
        except Exception as e:
            logger.warning(f'[知识包] 读取画风 README 失败 {d.name}: {e}')
        return pack

    def _load_yaml_list(self, path: Path, key: str) -> list[dict[str, Any]]:
        """解析 YAML 中指定 key 的列表，失败返回空列表。"""
        try:
            if not path.exists():
                return []
            with open(path, encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            items = data.get(key) or []
            return items if isinstance(items, list) else []
        except Exception as e:
            logger.warning(f'[知识包] YAML 解析失败 {path.name}: {e}')
            return []

    # ------------------------------------------------------------------
    # 题材映射（与 RedLineEngine 同源，单一事实来源）
    # ------------------------------------------------------------------

    def map_genre_to_theme(self, genre: str) -> str | None:
        """将项目 genre 映射到题材包 ID。

        支持键：xianxia/修仙/仙侠/fantasy、urban/都市/职场/workplace、
               suspe/悬疑/惊悚/thriller。
        """
        if not genre:
            return None
        if genre in self._genre_map_cache:
            return self._genre_map_cache[genre]
        genre_l = genre.lower()
        mapping = {
            'xianxia': 'xianxia_fantasy',
            '修仙': 'xianxia_fantasy',
            '仙侠': 'xianxia_fantasy',
            'fantasy': 'xianxia_fantasy',
            'urban': 'urban_workplace',
            '都市': 'urban_workplace',
            '职场': 'urban_workplace',
            'workplace': 'urban_workplace',
            'suspe': 'suspense_thriller',
            '悬疑': 'suspense_thriller',
            '惊悚': 'suspense_thriller',
            'thriller': 'suspense_thriller',
        }
        theme = next((t for k, t in mapping.items() if k in genre_l), None)
        self._genre_map_cache[genre] = theme
        return theme

    # ------------------------------------------------------------------
    # 对外查询
    # ------------------------------------------------------------------

    def list_theme_packs(self) -> list[str]:
        """列出已发现的题材包 ID。"""
        self._discover()
        return sorted(self._theme_packs.keys())

    def list_style_packs(self) -> list[str]:
        """列出已发现的画风包 ID。"""
        self._discover()
        return sorted(self._style_packs.keys())

    def get_theme_pack(self, theme_id: str) -> KnowledgePack | None:
        """按题材包 ID 获取知识包（不存在返回 None）。"""
        self._discover()
        return self._theme_packs.get(theme_id)

    def get_pack_for_genre(self, genre: str) -> KnowledgePack | None:
        """按项目 genre 自动匹配题材知识包（未映射返回 None）。

        Args:
            genre: 项目类型（'novel'/'comic'）或题材关键词（'仙侠'/'都市'/'悬疑'）

        Returns:
            匹配到的知识包；未匹配返回 None（流程降级但不报错）
        """
        theme_id = self.map_genre_to_theme(genre)
        if not theme_id:
            return None
        return self.get_theme_pack(theme_id)

    def get_fix_strategies_for_genre(self, genre: str) -> list[dict[str, Any]]:
        """获取题材专属修复策略（用于决策层 auto_fix 策略挑选）。

        Returns:
            修复策略列表（未匹配题材或缺失时返回空列表）
        """
        pack = self.get_pack_for_genre(genre)
        return list(pack.fix_strategies) if pack else []

    def get_style_pack(self, style_id: str) -> KnowledgePack | None:
        """按画风包 ID 获取画风知识包（不存在返回 None）。"""
        self._discover()
        return self._style_packs.get(style_id)

    def get_agent_skill(self, skill_name: str) -> str:
        """读取 Agent 技能卡 Markdown 全文（供上下文注入）。

        Args:
            skill_name: 技能名（如 'decision_agent_skill'，不含 .md）

        Returns:
            技能 Markdown；不存在返回空字符串
        """
        try:
            skill_path = _PACKS_ROOT / 'agent_skills' / f'{skill_name}.md'
            if not skill_path.exists():
                return ''
            return skill_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning(f'[知识包] 读取技能卡失败 {skill_name}: {e}')
            return ''

    def build_agent_context(self, genre: str, skill_name: str = '') -> dict[str, Any]:
        """组装 Agent 上下文（题材知识 + 可选技能卡），供 LLM 提示词注入。

        Args:
            genre: 项目类型/题材关键词
            skill_name: 可选技能卡名（如 'decision_agent_skill'）

        Returns:
            {'genre', 'theme_pack', 'skill_card'} — 缺失项为空字符串/None
        """
        self._discover()
        pack = self.get_pack_for_genre(genre)
        if pack:
            context = {
                'genre': genre,
                'theme_pack': pack.to_dict(),
                'narrative_techniques': pack.narrative_techniques[:1500]
                if pack.narrative_techniques else '',
                'fix_strategies': pack.fix_strategies,
                'red_lines': pack.red_lines,
                'skill_card': self.get_agent_skill(skill_name) if skill_name else '',
            }
        else:
            context = {
                'genre': genre,
                'theme_pack': None,
                'narrative_techniques': '',
                'fix_strategies': [],
                'red_lines': [],
                'skill_card': self.get_agent_skill(skill_name) if skill_name else '',
            }
        return context


# 模块级单例
knowledge_pack_loader = KnowledgePackLoader()