"""段落格式维度 — scan + fix + verify 自包含。"""

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.services.pm.dims.base import DimensionBase


class ParagraphFormatDimension(DimensionBase):
    name = 'paragraph_format'
    issue_type = 'pm_agent_paragraph_too_long'
    severity = 'warning'

    PARAGRAPH_MAX_CHARS = 110
    LONG_THRESHOLD = 3

    async def scan(self, db: AsyncSession, project_id: str, user_id: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        try:
            result = await db.execute(
                text("""
                    SELECT id, chapter_number, content FROM chapters
                    WHERE project_id = :pid AND content IS NOT NULL AND length(content) > 200
                    ORDER BY chapter_number DESC LIMIT 1
                """),
                {'pid': project_id},
            )
            row = result.fetchone()
            if not row:
                return issues
            chapter_id, chapter_number, content = row[0], row[1], row[2] or ''
            paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
            long_paras = [p for p in paragraphs if len(p) > self.PARAGRAPH_MAX_CHARS]
            if len(long_paras) > self.LONG_THRESHOLD:
                issues.append(
                    {
                        'type': 'paragraph_too_long',
                        'chapter_number': chapter_number,
                        'chapter_id': str(chapter_id),
                        'long_para_count': len(long_paras),
                        'total_paras': len(paragraphs),
                        'sample': (long_paras[0][:80] + '...') if long_paras else '',
                    }
                )
        except Exception:  # noqa: S110 — 扫描阶段任何异常都不应中断整体巡检，直接视为无问题
            pass
        return issues

    async def fix(self, issue: dict[str, Any], project_id: str, user_id: str, db: AsyncSession) -> str:
        from app.models.chapter import Chapter
        from sqlalchemy import select

        chapter_number = issue.get('chapter_number', 0) or 0
        ch_num = chapter_number if isinstance(chapter_number, int) else 0

        ch_result = await db.execute(
            select(Chapter).where(Chapter.project_id == project_id, Chapter.chapter_number == ch_num).order_by(Chapter.created_at.desc()).limit(1)
        )
        chapter = ch_result.scalar_one_or_none()
        if not chapter:
            return f'段落格式修复跳过（章节 {ch_num} 不存在）'

        content = chapter.content or ''
        if not content.strip():
            return f'段落格式修复跳过（章节 {ch_num} 内容为空）'

        try:
            from app.api.chapters._helpers._format import format_webnovel_paragraphs

            formatted = format_webnovel_paragraphs(content)
            if formatted == content:
                return f'段落格式修复跳过（章节 {ch_num} 已合规）'

            chapter.content = formatted
            chapter.word_count = len(formatted)
            await db.flush()

            old_long = len([p for p in content.split('\n\n') if len(p.strip()) > 110])
            new_long = len([p for p in formatted.split('\n\n') if len(p.strip()) > 110])

            return f'段落格式修复完成（第{ch_num}章）：超长段落 {old_long} -> {new_long}'
        except Exception as e:
            return f'段落格式修复异常: {e}'

    def diag_msg(self, issue: dict[str, Any]) -> str:
        return f'[PM-Agent] 第{issue.get("chapter_number", "?")}章有 {issue.get("long_para_count", 0)} 个超长段落（>{self.PARAGRAPH_MAX_CHARS}字）'
