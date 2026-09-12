"""主动汇报器 — 发现问题后主动推送，支持定时汇总"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import logging

logger = logging.getLogger(__name__)


@dataclass
class ReportItem:
    """单条预警项"""

    type: str  # foreshadow_overdue / character_missing / main_plot_stagnant / ooc_violation / milestone
    severity: str  # critical / high / medium / low
    msg: str
    suggestion: str = ''
    chapter_number: int | None = None


@dataclass
class Report:
    """汇报（可含多条预警）"""

    items: list[ReportItem] = field(default_factory=list)
    report_type: str = 'alert'  # alert / daily_summary / milestone

    @property
    def has_critical(self) -> bool:
        return any(i.severity == 'critical' for i in self.items)

    @property
    def summary(self) -> str:
        if not self.items:
            return '一切正常'
        critical = sum(1 for i in self.items if i.severity == 'critical')
        high = sum(1 for i in self.items if i.severity == 'high')
        parts = []
        if critical:
            parts.append(f'{critical}个严重')
        if high:
            parts.append(f'{high}个高危')
        if not parts:
            parts.append(f'{len(self.items)}个提醒')
        return '、'.join(parts)

    def to_response(self) -> dict:
        return {
            'type': self.report_type,
            'summary': self.summary,
            'has_critical': self.has_critical,
            'items': [
                {'type': i.type, 'severity': i.severity, 'msg': i.msg, 'suggestion': i.suggestion, 'chapter_number': i.chapter_number}
                for i in self.items
            ],
        }


class ProactiveReporter:
    """主动汇报器 — 从 Guardian + OOC 数据生成预警"""

    async def check(self, project_id: str, user_id: str, db: AsyncSession) -> Report:
        """运行一次完整检查，返回预警报告"""
        from app.models.chapter import Chapter
        from app.models.foreshadow import Foreshadow
        from app.models.character import Character
        from app.models.story_line import StoryLine
        from app.models.project import Project
        from app.models.ooc_violation import OOCViolation as OOCModel
        from app.services.guardian.long_novel_guardian import guardian

        report = Report()

        p_r = await db.execute(select(Project).where(Project.id == project_id))
        project = p_r.scalar_one_or_none()
        if not project:
            return report

        ch_r = await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number))
        chapters = list(ch_r.scalars().all())
        char_r = await db.execute(select(Character).where(Character.project_id == project_id))
        chars = list(char_r.scalars().all())
        f_r = await db.execute(select(Foreshadow).where(Foreshadow.project_id == project_id))
        fws = list(f_r.scalars().all())
        sl_r = await db.execute(select(StoryLine).where(StoryLine.project_id == project_id))
        sls = list(sl_r.scalars().all())

        # 1. LongNovelGuardian 扫描
        g_report = await guardian.scan(project, chapters, chars, fws, sls)
        for i in g_report.issues:
            if i.severity in ('critical', 'high'):
                report.items.append(
                    ReportItem(
                        type=i.type,
                        severity=i.severity,
                        msg=i.msg,
                        suggestion=i.suggestion,
                        chapter_number=i.chapter_number,
                    )
                )

        # 2. OOC 未解决违规
        try:
            ooc_r = await db.execute(
                select(OOCModel)
                .where(
                    OOCModel.project_id == project_id,
                    OOCModel.status == 'open',
                    OOCModel.severity.in_(['high', 'critical']),
                )
                .order_by(OOCModel.created_at.desc())
                .limit(5)
            )
            for ooc in ooc_r.scalars().all():
                report.items.append(
                    ReportItem(
                        type='ooc_violation',
                        severity=ooc.severity,
                        msg=f'[OOC] {ooc.excerpt[:60]}',
                        suggestion=ooc.suggestion or '',
                    )
                )
        except Exception as e:
            logger.warning(f'[proactive_reporter] check 失败: {e}')

        return report

    async def daily_summary(self, project_id: str, user_id: str, db: AsyncSession) -> Report:
        """每日汇总"""
        from app.models.chapter import Chapter
        from app.models.project import Project

        p_r = await db.execute(select(Project).where(Project.id == project_id))
        project = p_r.scalar_one_or_none()

        ch_r = await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number))
        chapters = list(ch_r.scalars().all())

        report = Report(report_type='daily_summary')
        total_ch = len(chapters)
        total_words = sum(len(c.content or '') for c in chapters)

        # 最近24小时完成的章节
        recent = [c for c in chapters if c.generated_at and c.generated_at > datetime.now() - timedelta(hours=24)]
        daily_ch = len(recent)
        daily_words = sum(len(c.content or '') for c in recent)

        target = project.target_words or 0
        progress_pct = round(total_words / target * 100, 1) if target > 0 else 0

        msg = f'今日完成 {daily_ch}章 / {daily_words}字 | 总进度 {total_ch}章 / {total_words}字' + (f' ({progress_pct}%)' if target > 0 else '')

        report.items.append(
            ReportItem(
                type='daily_stats',
                severity='low',
                msg=msg,
            )
        )

        # 同时跑一次检查
        alert_report = await self.check(project_id, user_id, db)
        if alert_report.items:
            report.items.extend(alert_report.items)

        return report

    async def milestone_check(self, project_id: str, user_id: str, db: AsyncSession) -> Report | None:
        """里程碑检测（每10章触发一次）"""
        from app.models.chapter import Chapter

        ch_r = await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number.desc()).limit(1))
        latest = ch_r.scalar_one_or_none()
        if not latest:
            return None

        cn = latest.chapter_number
        if cn % 10 != 0:
            return None  # 不是10的倍数

        report = Report(report_type='milestone')
        report.items.append(
            ReportItem(
                type='milestone',
                severity='low',
                msg=f'里程碑达成！已写至第{cn}章',
                chapter_number=cn,
            )
        )
        return report


reporter = ProactiveReporter()
