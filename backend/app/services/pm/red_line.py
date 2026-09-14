"""PM 红线系统 — 硬性质量约束（参考 ToonFlow 短剧通用红线设计）。

红线 = 一旦触发必须转人工介入的质量事件，禁止自动修复。

数据来源：
1. 全局红线：pm_features.yaml 顶层 red_lines 段（跨题材生效）
2. 题材红线：data/knowledge_packs/story_themes/*/red_lines.yaml（按 genre 加载）

核心接口：
- RedLineRule: 红线规则数据类
- RedLineEngine: 红线检测引擎（加载全局 + 题材红线，检测 issue 是否命中）
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

import yaml

logger = logging.getLogger(__name__)


@dataclass
class RedLineRule:
    """红线规则数据类。

    Attributes:
        id: 红线唯一标识（如 'RL-001' / 'XF-R1'）
        name: 规则名称
        description: 规则描述
        severity: 命中后 issue 的严重级别（一般为 critical）
        check_keywords: 关键词列表（正文包含任一关键词即命中，可为空则走函数检测）
        note: 补充说明（触发条件）
        source: 规则来源（'global' | 题材包 id）
    """

    id: str
    name: str = ''
    description: str = ''
    severity: str = 'critical'
    check_keywords: list[str] = field(default_factory=list)
    note: str = ''
    source: str = 'global'

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict。"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'severity': self.severity,
            'check_keywords': self.check_keywords,
            'note': self.note,
            'source': self.source,
        }

    def matches_text(self, text: str) -> bool:
        """关键词匹配检测 — 正文包含任一关键词即命中。

        Args:
            text: 待检测文本（如章节正文）

        Returns:
            是否命中（无关键词时返回 False，由函数检测器处理）
        """
        if not self.check_keywords or not text:
            return False
        for kw in self.check_keywords:
            if kw and kw in text:
                return True
        return False


class RedLineEngine:
    """红线检测引擎 — 加载全局 + 题材红线，统一检测入口。

    用法:
        engine = RedLineEngine()
        lines = engine.get_rules_for_genre('xianxia_fantasy')
        hit = engine.check_keywords(lines, '他发色突然变为金色...')
    """

    _instance = None
    _global_rules: list[RedLineRule] = []
    _theme_rules_cache: dict[str, list[RedLineRule]] = {}
    _loaded = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_global_rules()
        return cls._instance

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def _load_global_rules(self) -> None:
        """从 pm_features.yaml 加载全局红线。"""
        if self._loaded:
            return
        try:
            from app.services.pm.feature_config import pm_feature_config

            cfg = pm_feature_config.get_red_lines_config()
            if not cfg.get('enabled', False):
                logger.info('[红线] 全局红线未启用')
                return
            rules = cfg.get('rules', [])
            self._global_rules = [
                RedLineRule(
                    id=r.get('id', ''),
                    name=r.get('name', ''),
                    description=r.get('description', ''),
                    severity=r.get('severity', 'critical'),
                    check_keywords=r.get('check_keywords', []),
                    note=r.get('note', ''),
                    source='global',
                )
                for r in rules
                if r.get('id')
            ]
            logger.info('[红线] 加载全局红线 %d 条', len(self._global_rules))
        except Exception as e:
            logger.warning(f'[红线] 全局红线加载失败: {e}')
            self._global_rules = []
        self._loaded = True

    def _load_theme_rules(self, theme_id: str) -> list[RedLineRule]:
        """从知识包加载题材红线（带缓存）。

        Args:
            theme_id: 题材包 ID（如 'xianxia_fantasy'）

        Returns:
            题材红线列表（加载失败返回空列表）
        """
        if theme_id in self._theme_rules_cache:
            return self._theme_rules_cache[theme_id]
        rules: list[RedLineRule] = []
        try:
            pack_path = (
                Path(__file__).parent.parent.parent
                / 'data' / 'knowledge_packs' / 'story_themes' / theme_id / 'red_lines.yaml'
            )
            if not pack_path.exists():
                return rules
            with open(pack_path, encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            for r in (data.get('red_lines') or []):
                if r.get('id'):
                    rules.append(
                        RedLineRule(
                            id=r['id'],
                            name=r.get('name', ''),
                            description=r.get('description', ''),
                            severity=r.get('severity', 'critical'),
                            check_keywords=r.get('check_keywords', []),
                            note=r.get('note', ''),
                            source=theme_id,
                        )
                    )
        except Exception as e:
            logger.warning(f'[红线] 题材红线加载失败 theme={theme_id}: {e}')
        self._theme_rules_cache[theme_id] = rules
        return rules

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_global_rules(self) -> list[RedLineRule]:
        """获取全局红线。"""
        return list(self._global_rules)

    def get_rules_for_genre(self, genre: str) -> list[RedLineRule]:
        """获取项目类型适用的全部红线（全局 + 题材）。

        Args:
            genre: 项目类型（'novel' / 'comic'）或题材 ID（'xianxia_fantasy'）

        Returns:
            合并后的红线列表（全局在前，题材在后）
        """
        rules = list(self._global_rules)
        # 题材包按 story_themes 目录下存在的包 ID 尝试加载
        theme_id = self._map_genre_to_theme(genre)
        if theme_id:
            rules.extend(self._load_theme_rules(theme_id))
        return rules

    def _map_genre_to_theme(self, genre: str) -> str | None:
        """将项目 genre 映射到题材包 ID。

        支持映射（可通过知识包目录动态发现扩展）：
        - 'xianxia' / '修仙' / '仙侠' → 'xianxia_fantasy'
        - 'urban' / '都市' / '职场' → 'urban_workplace'
        - 'suspense' / '悬疑' / '惊悚' → 'suspense_thriller'
        """
        if not genre:
            return None
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
        for key, theme in mapping.items():
            if key in genre_l:
                return theme
        return None

    # ------------------------------------------------------------------
    # 检测
    # ------------------------------------------------------------------

    def check_keywords(self, rules: list[RedLineRule], text: str) -> list[RedLineRule]:
        """关键词检测 — 返回命中的红线规则列表。

        Args:
            rules: 红线规则列表
            text: 待检测文本

        Returns:
            命中的红线规则（按 id 去重）
        """
        if not text:
            return []
        hits: dict[str, RedLineRule] = {}
        for rule in rules:
            if rule.matches_text(text):
                hits[rule.id] = rule
        return list(hits.values())

    def make_issue(self, rule: RedLineRule, context: dict[str, Any]) -> dict[str, Any]:
        """将红线命中转换为标准 issue 字典（供扫描维度输出）。

        Args:
            rule: 命中的红线规则
            context: 上下文信息（如 chapter_number / project_id）

        Returns:
            issue 字典（含 red_line_id 标记）
        """
        return {
            'type': 'red_line_violation',
            'red_line_id': rule.id,
            'red_line_name': rule.name,
            'severity': rule.severity,
            'message': f'命中红线「{rule.name}」: {rule.description}',
            'chapter_number': context.get('chapter_number', 0),
            'chapter_id': context.get('chapter_id', ''),
            'red_line_source': rule.source,
            'suggestion': '命中红线，必须转为人工处理，禁止自动修复',
        }


# 全局单例
red_line_engine = RedLineEngine()