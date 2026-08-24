"""连续性审计服务 - AI驱动版本"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.chapter import Chapter
from app.models.project import Project
from app.models.character import Character
from app.models.golden_finger import GoldenFinger
from app.models.outline import Outline
from app.logger import get_logger
from app.services.ai.ai_service import AIService
from app.core import json_utils as json

logger = get_logger(__name__)

DIMENSIONS = {
    'character_consistency': '角色一致性',
    'power_level': '能力/金手指一致性',
    'timeline': '时间线逻辑',
    'relationship': '称谓/关系一致性',
    'world_rule': '世界观规则遵守',
}


class ContinuityIssue:
    def __init__(self, dimension: str, severity: str, description: str, suggestion: str | None = None):
        """初始化

        Args:
            self:
            dimension:
            severity:
            description:
            suggestion:

        Returns:
            None
        """
        self.dimension = dimension
        self.dimension_label = DIMENSIONS.get(dimension, dimension)
        self.severity = severity
        self.description = description
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        """ToDict

        Args:
            self:

        Returns:
            dict
        """
        return {
            'dimension': self.dimension,
            'dimension_label': self.dimension_label,
            'severity': self.severity,
            'description': self.description,
            'suggestion': self.suggestion,
        }


class ContinuityReport:
    def __init__(self, chapter_id: str, chapter_number: int):
        """初始化

        Args:
            self:
            chapter_id:
            chapter_number:

        Returns:
            None
        """
        self.chapter_id = chapter_id
        self.chapter_number = chapter_number
        self.issues: list[ContinuityIssue] = []
        self.summary = ''
        self.score = 100

    def add_issue(self, issue: ContinuityIssue):
        self.issues.append(issue)
        penalty = {'high': 15, 'medium': 8, 'low': 3}
        self.score = max(0, self.score - penalty.get(issue.severity, 5))

    def to_dict(self) -> dict:
        """ToDict

        Args:
            self:

        Returns:
            dict
        """
        return {
            'chapter_id': self.chapter_id,
            'chapter_number': self.chapter_number,
            'score': self.score,
            'total_issues': len(self.issues),
            'issues': [i.to_dict() for i in self.issues],
            'summary': self.summary,
        }


class ContinuityService:
    async def audit_chapter(
        self,
        chapter_id: str,
        db: AsyncSession,
        ai_service: AIService | None = None,
    ) -> ContinuityReport:
        """Audit章节

        Args:
            self:
            chapter_id:
            db:
            ai_service:

        Returns:
            ContinuityReport
        """
        ch = (await db.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none()
        if not ch:
            raise ValueError('章节不存在')

        report = ContinuityReport(chapter_id=ch.id, chapter_number=ch.chapter_number)
        if not ch.content or len(ch.content.strip()) < 200:
            report.summary = '章节内容过短，无法有效审计'
            return report

        proj = (await db.execute(select(Project).where(Project.id == ch.project_id))).scalar_one_or_none()
        if not proj:
            report.summary = '项目不存在'
            return report

        if not ai_service:
            report.summary = '未配置AI服务，跳过审计'
            return report

        context = await self._build_context(ch, proj, db)
        prompt = self._build_prompt(ch, proj, context)

        try:
            r = await ai_service.generate_text(prompt=prompt, temperature=0.3, max_tokens=2000, auto_mcp=False)
            raw = r.get('content', '') if isinstance(r, dict) else str(r)
            import re

            raw = re.sub(r'```(?:json)?\s*', '', raw).strip().strip('`').strip()
            data = json.loads(raw) if raw.startswith('{') else {}
            for item in data.get('issues', []):
                report.add_issue(
                    ContinuityIssue(
                        dimension=item.get('dimension', 'unknown'),
                        severity=item.get('severity', 'low'),
                        description=item.get('description', ''),
                        suggestion=item.get('suggestion', ''),
                    )
                )
            report.summary = data.get('summary', f'审计完成，发现 {len(report.issues)} 个问题')
        except Exception as e:
            logger.warning(f'AI连续性审计失败: {e}')
            report.summary = f'审计异常: {str(e)[:80]}'

        # OOC深度检测（增强版 character_consistency）
        try:
            from app.services.guardian.ooc_detector import ooc_detector
            from app.models.character import Character

            char_r = await db.execute(select(Character).where(Character.project_id == proj.id))
            all_chars = list(char_r.scalars().all())
            ooc_violations = await ooc_detector.scan_and_detect(ch, all_chars, ai_service)
            if ooc_violations:
                for v in ooc_violations:
                    report.add_issue(
                        ContinuityIssue(
                            dimension='character_consistency',
                            severity=v.severity,
                            description=f'[OOC][{v.char_name}] {v.reason}（原文：{v.excerpt}）'[:200],
                            suggestion=v.suggestion[:200],
                        )
                    )
                # 存库
                char_map = {c.name: c.id for c in all_chars}
                await ooc_detector.save_violations(proj.id, ch.id, ooc_violations, char_map, db)
                logger.info(f'OOC检测完成: 发现{len(ooc_violations)}个违规')
        except Exception as e_ooc:
            logger.warning(f'OOC深度检测异常: {e_ooc}')

        return report

    async def _build_context(self, ch: Chapter, proj: Project, db: AsyncSession) -> dict:
        """构建上下文

        Args:
            self:
            ch:
            proj:
            db:

        Returns:
            dict
        """
        ctx = {}
        prev = (
            (
                await db.execute(
                    select(Chapter)
                    .where(
                        Chapter.project_id == ch.project_id,
                        Chapter.chapter_number < ch.chapter_number,
                        Chapter.chapter_number >= ch.chapter_number - 3,
                    )
                    .order_by(Chapter.chapter_number)
                )
            )
            .scalars()
            .all()
        )
        ctx['prev'] = '\n'.join(f'第{p.chapter_number}章《{p.title}》: {(p.summary or p.content or "")[:300]}' for p in prev) or '无'

        chars = (await db.execute(select(Character).where(Character.project_id == ch.project_id))).scalars().all()
        ctx['chars'] = (
            '\n'.join(f'{c.name}（{"主角" if c.role_type == "protagonist" else "反派" if c.role_type == "antagonist" else "配角"}）' for c in chars)
            or '无'
        )

        gfs = (await db.execute(select(GoldenFinger).where(GoldenFinger.project_id == ch.project_id))).scalars().all()
        ctx['gfs'] = (
            '\n'.join(
                f'{gf.name}: {gf.core_functions[:200] if gf.core_functions else ""}'
                f'{"（限制: " + gf.limitations_costs[:200] + "）" if gf.limitations_costs else ""}'
                for gf in gfs
            )
            or '无'
        )

        ol = (
            await db.execute(
                select(Outline)
                .where(
                    Outline.project_id == ch.project_id,
                    Outline.order_index == ch.chapter_number,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        ctx['ol'] = (ol.content or '')[:500] if ol else '无'
        return ctx

    def _build_prompt(self, ch: Chapter, proj: Project, ctx: dict) -> str:
        """构建Prompt

        Args:
            self:
            ch:
            proj:
            ctx:

        Returns:
            str
        """
        return f"""作为专业连续性审计员，检查本章是否存在与前后文矛盾的问题。

项目：{proj.title}
章节：第{ch.chapter_number}章《{ch.title}》
叙事视角：{proj.narrative_perspective or '第三人称'}
世界观：{proj.world_rules or '未设定'}

【前3章摘要】
{ctx['prev']}

【本章大纲】
{ctx['ol']}

【项目角色】
{ctx['chars']}

【金手指设定】
{ctx['gfs']}

【本章内容】
{ch.content[:3000]}

请从以下5个维度检查连续性问题：

1. character_consistency（角色一致性）：前文已死/消失的角色是否出现？角色行为是否偏离已设定的性格？
2. power_level（能力/金手指一致性）：角色使用的能力是否超出已有设定？金手指限制是否被遵守？
3. timeline（时间线逻辑）：事件顺序是否合理？时间是否与前章衔接？
4. relationship（称谓/关系一致性）：称呼和关系是否与前文一致？
5. world_rule（世界观规则遵守）：是否遵守了已设定的世界规则？

要求：宁严勿宽。不确定的问题也列出来，标低严重度即可。

返回JSON：
{{"summary":"总体评价","issues":[
  {{"dimension":"character_consistency","severity":"high|medium|low","description":"问题描述","suggestion":"修改建议"}}
]}}"""


continuity_service = ContinuityService()
