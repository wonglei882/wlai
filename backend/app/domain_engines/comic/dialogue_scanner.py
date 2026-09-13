"""对话气泡一致性扫描器 — 检测角色语气/口癖跨分镜一致性。

对比同一角色在不同分镜中的对话文本，
检测语气风格是否发生不合理变化（如：一贯文雅的角色突然说粗话）。
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pm.scanner_base import BaseScanner, ScanIssue

import logging

logger = logging.getLogger(__name__)

# 语气标记词（简单规则版，后续可接入 AI 语义分析）
_FORMAL_MARKERS = {'请', '您', '阁下', '在下', '鄙人', '承蒙', '岂敢'}
_INFORMAL_MARKERS = {'你', '老子', '爷', '俺', '咱', '喂', '哈'}


class DialogueBubbleScanner(BaseScanner):
    """对话气泡一致性扫描 — 检测角色语气风格跳变。"""

    name = 'dialogue_bubble'
    issue_type = 'ca_dialogue_inconsistency'

    async def scan(
        self, db: AsyncSession, project_id: str, user_id: str
    ) -> list[ScanIssue]:
        """检测角色对话语气风格变化。"""
        issues: list[ScanIssue] = []
        try:
            result = await db.execute(
                text("""
                    SELECT id, global_sequence, dialogue
                    FROM comic_panels
                    WHERE project_id = :pid
                      AND dialogue IS NOT NULL
                    ORDER BY global_sequence ASC
                    LIMIT 50
                """),
                {'pid': project_id},
            )
            rows = result.fetchall()

            # 按角色聚合对话风格
            char_styles: dict[str, list[tuple[int, str]]] = {}  # name -> [(seq, style)]
            for row in rows:
                seq, dialogue_list = row[1], row[2] or []
                for d in dialogue_list:
                    name = d.get('character', '')
                    text_content = d.get('text', '')
                    if not name or not text_content:
                        continue
                    style = self._classify_style(text_content)
                    char_styles.setdefault(name, []).append((seq, style))

            # 检测同一角色的风格跳变
            for name, style_seq in char_styles.items():
                for i in range(1, len(style_seq)):
                    prev_seq, prev_style = style_seq[i - 1]
                    curr_seq, curr_style = style_seq[i]
                    if prev_style != curr_style and prev_style and curr_style:
                        issues.append(
                            ScanIssue(
                                issue_type='ca_dialogue_inconsistency',
                                severity='warning',
                                message=f'角色「{name}」语气跳变: {prev_style}→{curr_style} (分镜 {prev_seq}→{curr_seq})',
                                entities=[f'character:{name}', f'panel:{prev_seq}', f'panel:{curr_seq}'],
                                metadata={
                                    'character': name,
                                    'style_from': prev_style,
                                    'style_to': curr_style,
                                },
                            )
                        )

        except Exception as e:
            logger.warning('[CA] 对话气泡扫描异常 project=%s: %s', project_id, e)
        return issues

    def _classify_style(self, text: str) -> str:
        """简单规则分类对话语气风格。"""
        formal_count = sum(1 for m in _FORMAL_MARKERS if m in text)
        informal_count = sum(1 for m in _INFORMAL_MARKERS if m in text)

        if formal_count > informal_count:
            return 'formal'
        if informal_count > formal_count:
            return 'informal'
        return 'neutral'

    def to_diagnostic_message(self, issue: ScanIssue) -> str:
        return f'[CA] {issue.message}'
