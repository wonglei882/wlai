"""OOC检测器 - 角色签名提取 + 章节扫描 + OOC比对 + 报告生成"""

import json
import re
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.character import Character
from app.models.chapter import Chapter
from app.models.ooc_violation import OOCViolation as OOCModel
from app.services.ai.ai_service import AIService
from app.services.guardian.continuity_service import ContinuityIssue

logger = get_logger(__name__)


@dataclass
class CharacterSignature:
    """角色签名——从数据库结构化数据提取的行为规范"""

    char_id: str
    name: str
    personality_traits: list[str] = field(default_factory=list)
    emotion_tendency: str = ''
    decision_style: str = ''
    speech_register: str = ''
    common_phrases: list[str] = field(default_factory=list)
    dialogue_patterns: str = ''
    behavior_patterns: list[str] = field(default_factory=list)
    forbidden_behaviors: list[str] = field(default_factory=list)


@dataclass
class OOCViolation:
    """OOC违规记录"""

    char_name: str
    char_id: str
    severity: str
    violation_type: str
    excerpt: str
    reason: str
    suggestion: str


class OOCDetector:
    """OOC检测器——从已有数据提取签名 → 扫描章节 → 逐角色比对"""

    async def extract_signature(self, char: Character) -> CharacterSignature:
        """从 Character 模型数据提取结构化签名"""
        traits = self._parse_personality(char.personality or '')
        speech = self._parse_speech(char.speaking_style or '', char.speech_patterns or '')
        behavior = self._infer_behavior(char.personality or '', char.background or '')
        return CharacterSignature(
            char_id=char.id,
            name=char.name,
            personality_traits=traits,
            emotion_tendency=self._infer_emotion(traits),
            decision_style=self._infer_decision_style(traits),
            speech_register=speech.get('register', ''),
            common_phrases=speech.get('phrases', []),
            dialogue_patterns=speech.get('patterns', ''),
            behavior_patterns=behavior.get('patterns', []),
            forbidden_behaviors=behavior.get('forbidden', []),
        )

    def _parse_personality(self, text: str) -> list[str]:
        """从性格描述提取关键词"""
        import jieba

        # 简单分词 + 停用词过滤
        stopwords = {'的', '了', '是', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '要', '会', '在', '没有', '但', '与'}
        words = [w for w in jieba.lcut(text) if len(w) >= 2 and w not in stopwords]
        return words[:8] if words else [text[:20]] if text else []

    def _parse_speech(self, style: str, patterns: str) -> dict:
        """解析说话风格"""
        result = {'register': '', 'phrases': [], 'patterns': ''}
        if patterns:
            try:
                parsed = json.loads(patterns) if isinstance(patterns, str) else patterns
                if isinstance(parsed, dict):
                    return {**result, **parsed}
            except Exception:
                logger.debug('[OOC] 说话风格 JSON 解析失败')
            result['patterns'] = patterns[:100]
        if style:
            if any(w in style for w in ['文雅', '古风', '文言', '书卷']):
                result['register'] = '文雅'
            elif any(w in style for w in ['粗犷', '豪放', '直白', '粗俗']):
                result['register'] = '粗犷'
            elif any(w in style for w in ['网络', '现代', '口语', '幽默']):
                result['register'] = '网络化'
            else:
                result['register'] = style[:20]
        return result

    def _infer_emotion(self, traits: list[str]) -> str:
        """推断情绪表达倾向"""
        if any(w in str(traits) for w in ['冷静', '理性', '沉稳', '内敛']):
            return '内敛——情绪表达克制'
        if any(w in str(traits) for w in ['冲动', '暴躁', '易怒', '直率']):
            return '外放——情绪表达直接'
        return '中性——视情况而定'

    def _infer_decision_style(self, traits: list[str]) -> str:
        """推断决策风格"""
        t = str(traits)
        if any(w in t for w in ['冲动', '急躁', '直率']):
            return '冲动'
        if any(w in t for w in ['谨慎', '理性', '沉稳', '多疑']):
            return '谨慎'
        if any(w in t for w in ['犹豫', '优柔', '温和']):
            return '犹豫'
        return '权衡利弊'

    def _infer_behavior(self, personality: str, background: str) -> dict:
        """从性格+背景推断行为规范"""
        patterns = []
        forbidden = []
        p = (personality + ' ' + background).lower()
        if any(w in p for w in ['冷静', '理性']):
            patterns.append('做决定前会分析利弊')
        if any(w in p for w in ['冲动', '暴躁']):
            patterns.append('遇到冲突会直接对抗')
        if any(w in p for w in ['谨慎']):
            patterns.append('遇到危险会先观察再行动')
        if any(w in p for w in ['善良', '温柔']):
            patterns.append('不忍心看他人受伤害')
        if any(w in p for w in ['骄傲', '自负']):
            patterns.append('不会轻易低头认输')
        if any(w in p for w in ['狡猾', '城府']):
            patterns.append('说话会留三分余地')
        if any(w in p for w in ['冲动', '暴躁']):
            forbidden.append('轻易流泪')
        if any(w in p for w in ['冷静', '理性']):
            forbidden.append('情绪失控')
        if any(w in p for w in ['骄傲', '自负']):
            forbidden.append('主动示弱')
        return {'patterns': patterns, 'forbidden': forbidden}

    async def scan_and_detect(
        self,
        chapter: Chapter,
        characters: list[Character],
        ai_service: AIService,
    ) -> list[OOCViolation]:
        """合并 scan + detect 为一次 LLM 调用"""
        if not chapter.content or len(chapter.content.strip()) < 200:
            return []

        # 提取角色签名
        sigs = []
        for c in characters:
            if c.is_organization:
                continue
            sig = await self.extract_signature(c)
            sigs.append(sig)

        if not sigs:
            return []

        # 角色列表文本
        char_list_text = '\n'.join(
            f'{s.name}：性格={",".join(s.personality_traits[:5])} 说话={s.speech_register} '
            f'常用词={",".join(s.common_phrases[:3])} 禁止={",".join(s.forbidden_behaviors[:3])}'
            for s in sigs
        )

        content_text = chapter.content[:6000] if len(chapter.content) > 6000 else chapter.content

        prompt = f"""你是角色一致性审查员。分析以下章节内容，对每个角色提取其对话和行为，然后判断是否存在OOC（偏离人设）的问题。

【角色人设】
{char_list_text}

【章节内容——第{chapter.chapter_number}章《{chapter.title}》】
{content_text}

请严格按以下JSON格式输出：
{{
  "scans": [
    {{
      "char_name": "角色名",
      "actions": [
        {{"type": "dialogue", "text": "台词内容"}},
        {{"type": "action", "text": "行为描写"}}
      ],
      "violations": [
        {{
          "severity": "high/medium/low",
          "type": "dialogue_ooc/action_ooc/emotion_ooc",
          "excerpt": "违规原文（30字以内）",
          "reason": "为什么这违规",
          "suggestion": "如何修改"
        }}
      ]
    }}
  ]
}}

规则：
- 只有确实存在违规时才输出 violations，没有就留空数组
- severity: high=严重人设崩塌 / medium=轻微偏离 / low=可疑但可接受
- 不要过度判断，角色可以有合理的性格发展
- 只输出JSON，不要其他内容"""

        try:
            r = await ai_service.generate_text(prompt=prompt, temperature=0.1, max_tokens=3000, auto_mcp=False)
            raw = r.get('content', '') if isinstance(r, dict) else str(r)
            raw = re.sub(r'```(?:json)?\s*', '', raw).strip().strip('`').strip()
            if raw.startswith('{'):
                data = json.loads(raw)
            else:
                brace = raw.find('{')
                data = json.loads(raw[brace:]) if brace >= 0 else {}
        except Exception as e:
            logger.warning(f'OOC检测解析失败: {e}')
            return []

        violations = []
        for scan in data.get('scans', []):
            for v in scan.get('violations', []):
                violations.append(
                    OOCViolation(
                        char_name=scan.get('char_name', ''),
                        char_id='',
                        severity=v.get('severity', 'low'),
                        violation_type=v.get('type', 'action_ooc'),
                        excerpt=v.get('excerpt', ''),
                        reason=v.get('reason', ''),
                        suggestion=v.get('suggestion', ''),
                    )
                )

        severity_order = {'high': 0, 'medium': 1, 'low': 2}
        violations.sort(key=lambda x: severity_order.get(x.severity, 3))
        return violations

    async def save_violations(
        self,
        project_id: str,
        chapter_id: str,
        violations: list[OOCViolation],
        char_map: dict[str, str],
        db: AsyncSession,
    ):
        """保存检测结果到数据库"""
        for v in violations:
            record = OOCModel(
                project_id=project_id,
                chapter_id=chapter_id,
                character_id=char_map.get(v.char_name, ''),
                severity=v.severity,
                violation_type=v.violation_type,
                excerpt=v.excerpt[:300],
                reason=v.reason[:500],
                suggestion=v.suggestion[:500],
            )
            db.add(record)
        await db.commit()
        logger.info(f'已保存 {len(violations)} 条OOC违规记录')

    def to_continuity_issues(self, violations: list[OOCViolation]) -> list[ContinuityIssue]:
        """转为 continuity_service 的 ContinuityIssue 格式"""
        issues = []
        for v in violations:
            issues.append(
                ContinuityIssue(
                    dimension='character_consistency',
                    severity=v.severity,
                    description=f'[OOC][{v.char_name}] {v.reason}（原文：{v.excerpt}）'[:200],
                    suggestion=v.suggestion[:200],
                )
            )
        return issues


ooc_detector = OOCDetector()
