"""长篇一致性守护者 — 伏笔追踪、角色戏份、时间线、主线推进检测
作为 supervise_project / auto_supervise / project_health 的统一底层引擎"""

import re
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.logger import get_logger
from app.agent.infrastructure.text_analysis import extract_keywords as _jieba_keywords

logger = get_logger(__name__)


@dataclass
class GuardianIssue:
    """检测结果条目"""

    type: str  # foreshadow_overdue / foreshadow_unresolved / character_missing / character_neglected / timeline_conflict / main_plot_stagnant
    severity: str  # critical / high / medium / low
    msg: str
    chapter_number: int | None = None
    target_id: str | None = None
    suggestion: str = ''


@dataclass
class GuardianReport:
    """检测报告"""

    issues: list[GuardianIssue] = field(default_factory=list)

    @property
    def total(self):
        return len(self.issues)

    @property
    def critical_count(self):
        return sum(1 for i in self.issues if i.severity == 'critical')

    @property
    def high_count(self):
        return sum(1 for i in self.issues if i.severity == 'high')

    def add(self, issue: GuardianIssue):
        self.issues.append(issue)

    def to_dict(self) -> dict:
        (
            """将检测报告转换为字典格式。

        Returns:
            包含 total、critical_count、high_count、score、issues 的字典
        """
            ''
        )
        score = max(0, 100 - self.critical_count * 20 - self.high_count * 5)
        return {
            'total': self.total,
            'critical_count': self.critical_count,
            'high_count': self.high_count,
            'issues': [{'type': i.type, 'severity': i.severity, 'msg': i.msg, 'suggestion': i.suggestion} for i in self.issues],
            'summary': {'score': score, 'critical': self.critical_count, 'warning': self.high_count, 'info': 0},
            'dimensions': {},
        }

    def to_logs(self, chapter_label: str = '') -> list[str]:
        """ToLogs

        Args:
            self:
            chapter_label:

        Returns:
            List[str]
        """
        if not self.issues:
            return [f'✅ {chapter_label}一致性检查通过'] if chapter_label else ['✅ 项目一致性检查通过']
        severity_label = {'critical': '🔴严重', 'high': '⚠️高', 'medium': '🟡中', 'low': '🔵低'}
        logs = [f'📋 {chapter_label}发现问题 ({self.total}项):']
        for i in self.issues:
            label = severity_label.get(i.severity, i.severity)
            logs.append(f'  [{label}] {i.msg}')
            if i.suggestion:
                logs.append(f'    建议: {i.suggestion}')
        return logs


_SEASON_KEYWORDS = {
    '春': ['春', '花开', '暖风', '春雨', '桃花', '柳绿'],
    '夏': ['夏', '炎热', '蝉鸣', '烈日', '酷暑', '汗'],
    '秋': ['秋', '落叶', '金黄', '秋风', '丰收', '枫叶'],
    '冬': ['冬', '寒冷', '雪花', '冰霜', '寒风', '白雪'],
}
_TIME_KEYWORDS = {
    '早': ['清晨', '早晨', '早上', '日出', '晨光'],
    '午': ['中午', '正午', '午时', '烈日当空'],
    '晚': ['傍晚', '黄昏', '夕阳', '暮色', '入夜', '夜幕'],
}
_STOP_WORDS = {
    '的',
    '了',
    '是',
    '在',
    '我',
    '有',
    '和',
    '就',
    '不',
    '人',
    '都',
    '一',
    '一个',
    '上',
    '也',
    '很',
    '到',
    '说',
    '要',
    '去',
    '你',
    '会',
    '着',
    '没有',
    '看',
    '好',
    '自己',
    '这',
    '那',
    '什么',
    '怎么',
    '因为',
    '所以',
    '但是',
    '如果',
    '虽然',
    '然后',
    '可以',
    '这个',
    '那个',
    '他们',
    '我们',
    '你们',
}


def _extract_keywords(text: str, top_n: int = 10) -> list[str]:
    """从文本提取关键词（纯词频，无外部依赖）"""
    if not text:
        return []
    words = re.findall(r'[\u4e00-\u9fff]{2,}', text)
    freq = {}
    for w in words:
        if w not in _STOP_WORDS:
            freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: -x[1])
    return [w for w, _ in sorted_words[:top_n]]


def _infer_season(text: str) -> str | None:
    """从文本推断季节"""
    if not text:
        return None
    for season, kws in _SEASON_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return season
    return None


class LongNovelGuardian:
    """长篇一致性守护者——统一引擎"""

    async def scan(
        self,
        project,
        chapters: list,
        characters: list,
        foreshadows: list,
        storylines: list,
    ) -> GuardianReport:
        """扫描全书/当前章节，返回所有问题"""
        report = GuardianReport()
        latest_n = chapters[-1].chapter_number if chapters else 0

        # 1. 伏笔追踪
        report.issues.extend(self._check_foreshadows(foreshadows, latest_n, chapters))

        # 2. 角色戏份
        report.issues.extend(self._check_characters(characters, chapters, latest_n))

        # 3. 时间线一致性
        if chapters:
            report.issues.extend(self._check_timeline(project, chapters))

        # 4. 主线推进
        report.issues.extend(self._check_main_plot(storylines, chapters, latest_n))

        # 排序：severity 高的在前
        sev_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        report.issues.sort(key=lambda x: sev_order.get(x.severity, 9))
        return report

    def _check_foreshadows(self, foreshadows: list, latest_n: int, chapters: list) -> list[GuardianIssue]:
        """伏笔追踪"""
        issues = []
        for f in foreshadows:
            if f.status not in ('pending', 'planted'):
                continue
            tc = f.target_resolve_chapter_number
            if tc and tc <= latest_n:
                overdue = latest_n - tc
                issues.append(
                    GuardianIssue(
                        type='foreshadow_overdue',
                        severity='critical' if overdue >= 3 else 'high',
                        msg=f'伏笔「{(f.title or "")[:40]}」超期{overdue}章未回收（计划第{tc}章）',
                        target_id=f.id,
                        suggestion='在当前或下一章处理该伏笔',
                    )
                )
            # 检测到期是否已处理
            if tc == latest_n and chapters:
                content = chapters[-1].content or ''
                if content:
                    kw = [w for w, _ in _jieba_keywords(f.content or '', 5)]
                    found = any(k in content for k in kw[:5])
                    if not found:
                        issues.append(
                            GuardianIssue(
                                type='foreshadow_unresolved',
                                severity='high',
                                msg=f'伏笔「{(f.title or "")[:40]}」计划本章回收但正文未体现',
                                target_id=f.id,
                                suggestion='在本章中加入相关线索',
                            )
                        )
        return issues

    def _check_characters(self, characters: list, chapters: list, latest_n: int) -> list[GuardianIssue]:
        """角色戏份检测"""
        issues = []
        if len(chapters) < 5:
            return issues

        recent = [c for c in chapters if c.chapter_number > max(0, latest_n - 10)]
        if not recent:
            return issues

        for char in characters:
            if char.is_organization or char.role_type not in ('protagonist', 'antagonist', 'supporting'):
                continue
            if char.status == 'deceased':
                continue

            total_mentions = sum((c.content or '').count(char.name) for c in recent)
            name = char.name

            if total_mentions == 0:
                issues.append(
                    GuardianIssue(
                        type='character_missing',
                        severity='high' if char.role_type == 'protagonist' else 'medium',
                        msg=f'「{name}」近10章零出场（'
                        f'{"主角" if char.role_type == "protagonist" else "反派" if char.role_type == "antagonist" else "配角"}）',
                        target_id=char.id,
                        suggestion=f'安排「{name}」在后续章节出场',
                    )
                )
            elif total_mentions < 20:
                issues.append(
                    GuardianIssue(
                        type='character_neglected',
                        severity='low',
                        msg=f'「{name}」近10章出场极少（仅{total_mentions}次提及）',
                        target_id=char.id,
                        suggestion=f'考虑给「{name}」增加戏份',
                    )
                )
        return issues

    def _check_timeline(self, project, chapters: list) -> list[GuardianIssue]:
        """时间线一致性"""
        issues = []
        if len(chapters) < 2:
            return issues
        latest = chapters[-1]
        content = latest.content or ''
        if not content:
            return issues

        # 从世界观推断故事季节
        world_season = _infer_season(project.world_time_period or '')
        chapter_season = _infer_season(content)
        if world_season and chapter_season and world_season != chapter_season:
            issues.append(
                GuardianIssue(
                    type='timeline_season_conflict',
                    severity='medium',
                    msg=f'本章出现「{chapter_season}季」描写，世界观设定为「{world_season}季」',
                    suggestion='确认季节是否有意推进，否则修正描写',
                )
            )

        # 检查角色死亡后是否被提及
        for c in chapters[-10:]:
            if c.id == latest.id:
                continue
            # 无需额外逻辑，OOCDetector 已处理
        return issues

    def _check_main_plot(self, storylines: list, chapters: list, latest_n: int) -> list[GuardianIssue]:
        """主线推进检测"""
        issues = []
        main_lines = [s for s in storylines if s.line_type == 'main']
        if not main_lines:
            return issues

        recent = [c for c in chapters if c.chapter_number > max(0, latest_n - 5)]
        if len(recent) < 3:
            return issues

        for line in main_lines:
            if line.status != 'active':
                continue
            kw = [w for w, _ in _jieba_keywords(line.description or '', 8)]
            has_progress = any(any(k in (c.content or '') for k in kw[:8]) for c in recent)
            if not has_progress:
                issues.append(
                    GuardianIssue(
                        type='main_plot_stagnant',
                        severity='high',
                        msg=f'主线「{line.name}」近5章无明显推进',
                        target_id=line.id,
                        suggestion='在当前章节加入主线推进事件',
                    )
                )
        return issues

    async def character_frequency(self, project_id: str, db: AsyncSession, recent_n: int = 10) -> dict:
        """统计近N章各角色出场频率"""
        from app.models.chapter import Chapter
        from app.models.character import Character

        ch_r = await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number.desc()).limit(recent_n))
        chapters = list(ch_r.scalars().all())
        chapters.reverse()

        char_r = await db.execute(
            select(Character).where(
                Character.project_id == project_id,
                Character.is_organization.is_(False),
            )
        )
        chars = list(char_r.scalars().all())

        result = {
            c.name: {
                'role': '主角' if c.role_type == 'protagonist' else '反派' if c.role_type == 'antagonist' else '配角',
                'total': 0,
                'per_chapter': {},
            }
            for c in chars
        }

        for ch in chapters:
            content = ch.content or ''
            for c in chars:
                count = content.count(c.name)
                result[c.name]['total'] += count
                result[c.name]['per_chapter'][f'第{ch.chapter_number}章'] = count

        # 按总出场排序
        sorted_result = dict(sorted(result.items(), key=lambda x: -x[1]['total']))
        return {
            'chapters': [f'第{c.chapter_number}章' for c in chapters],
            'characters': sorted_result,
        }


guardian = LongNovelGuardian()
