"""强化版质量评分器 — 7维评分 + 改进建议 + 自动重试闭环"""

import json
import math
import re as _re_q

from app.logger import get_logger
from app.services.ai.ai_service import AIService

# P0 修复：safe_int 未导入导致 468 次异常（name 'safe_int' is not defined）
from app.services.json_helper import safe_int

logger = get_logger(__name__)


class ScoreResult:
    def __init__(
        self,
        scores: dict,
        suggestions: list,
        passed: bool,
        causal_density: float = 0.0,
        conflict_intensity: float = 0.0,
        foreshadow_density: float = 0.0,
        total_score: float = None,
    ):
        """初始化

        Args:
            self:
            scores:
            suggestions:
            passed:
            causal_density:
            conflict_intensity:
            foreshadow_density:
            total_score:

        Returns:
            None
        """
        self.scores = scores
        self.suggestions = suggestions
        self.passed = passed
        # total_score 由 PMQualityScorerV2.score() 传入（加权分，与 PASS_THRESHOLD 对齐）
        self.total_score = total_score if total_score is not None else (sum(scores.values()) / len(scores) if scores else 0)
        self.failed_dimensions = [k for k, v in scores.items() if v < 60]
        self.causal_density = causal_density
        self.conflict_intensity = conflict_intensity
        self.foreshadow_density = foreshadow_density


class PMQualityScorerV2:
    """强化版质量评分器"""

    DEFAULT_DIMENSIONS = {
        'pacing': 0.15,
        'dialogue': 0.10,
        'hook': 0.15,
        'character_consistency': 0.20,
        'plot_logic': 0.15,
        'emotional_curve': 0.10,
        'outline_adherence': 0.15,
    }
    PASS_THRESHOLD = 70
    MAX_RETRIES = 3

    def __init__(self, ai_service: AIService = None, weights: dict = None):
        """ai_service: AI服务实例（用于调用评分）
        weights: 动态权重 dict，若为 None 则使用默认 DIMENSIONS。
                  从 PMSessionState.extra_data.quality_weights 读取。
        """
        self.ai = ai_service
        self._weights = weights  # None = 使用 DEFAULT_DIMENSIONS

    @property
    def DIMENSIONS(self) -> dict:
        """支持实例级动态权重，L4-A 自调优会传入自定义权重。"""
        return self._weights if self._weights else self.DEFAULT_DIMENSIONS

    async def score(self, content: str, context: dict) -> ScoreResult:
        """7维评分 + 改进建议"""
        scores = {}
        suggestions = []

        # 调用 AI 评分
        if self.ai and content:
            try:
                dims = ', '.join(self.DIMENSIONS.keys())
                # 采样：取前1/3 + 末尾500字（覆盖首尾两端）
                _sample_len = min(1500, max(len(content) // 3, 500))
                scoring_sample = content[:_sample_len] + '\n[以上为章节开头，以下为章节结尾]\n' + content[-500:]
                prompt = f"""对以下章节内容进行7维度评分（0-100），输出JSON。

注意：以下内容包含章节开头和结尾片段。如果章节很短则从头到尾全部评分。

维度：{dims}

内容：
{scoring_sample}

章纲：
{context.get('seq_table', '')[:500]}

输出JSON格式：{{"pacing": 70, "dialogue": 60, ...}}"""
                # P0: 经 call_llm_with_guard 加超时 + 熔断，防 AI 服务卡死阻塞整个评分流程
                from app.services.pm.pm_llm_guard import call_llm_with_guard

                r = await call_llm_with_guard(
                    self.ai.generate_text,
                    breaker_name='quality_scorer',
                    prompt=prompt,
                    temperature=0.1,
                    max_tokens=500,
                    auto_mcp=False,
                )
                if not r:
                    raise RuntimeError('AI 评分调用失败/超时（已熔断或回退到规则评分）')
                raw = str(r.get('content', '')) if isinstance(r, dict) else str(r)
                m = _re_q.search(r'\{.*\}', raw, _re_q.DOTALL)
                if m:
                    parsed = json.loads(m.group())
                    for dim in self.DIMENSIONS:
                        scores[dim] = min(100, max(0, safe_int(parsed.get(dim, 70), 70)))
            except Exception as e:
                logger.warning(f'AI评分失败: {e}')

        # Fallback: 规则评分
        if not scores:
            wc = len(content)
            para_count = content.count('\n\n') + 1
            scores['pacing'] = min(100, int(wc / max(para_count, 1) * 2)) if para_count else 60
            scores['dialogue'] = 60
            # 修复：仅识别 ASCII '?' 会让中文全角问号「？」的强钩子章节漏判（网文高频标点）
            scores['hook'] = 80 if ('?' in content[:500] or '？' in content[:500]) else 50
            scores['character_consistency'] = 70
            scores['plot_logic'] = 70
            scores['emotional_curve'] = 60
            scores['outline_adherence'] = 80 if context.get('seq_table') else 60

        # 生成改进建议
        for dim, score in scores.items():
            if score < 60:
                suggestions.append(f'{dim}: {score}分 — 需改进')
            elif score < 80:
                suggestions.append(f'{dim}: {score}分 — 良好')

        passed = self.total_score(scores) >= self.PASS_THRESHOLD

        # B方案新增指标：规则计算（不调 AI，零额外成本）
        causal_d = self._compute_causal_density(content)
        conflict_i = self._compute_conflict_intensity(content)
        foreshadow_d = self._compute_foreshadow_density(content)

        # 传加权分（与 passed 判断一致）
        weighted_total = self.total_score(scores)
        return ScoreResult(
            scores,
            suggestions[:3],
            passed,
            causal_density=causal_d,
            conflict_intensity=conflict_i,
            foreshadow_density=foreshadow_d,
            total_score=weighted_total,
        )

    def total_score(self, scores: dict) -> float:
        """加权总分（0~100），显式归一化。

        注意：DEFAULT_DIMENSIONS 权重和=1.0，恰好归一；
        但用户若传入自定义 weights 且和≠1.0，/ sum(...) 会自动归一，
        结果与 PASS_THRESHOLD=70 的比较仍然有效。
        """
        weight_sum = sum(self.DIMENSIONS.values())
        return sum(scores.get(dim, 0) * weight for dim, weight in self.DIMENSIONS.items()) / weight_sum

    def _compute_causal_density(self, content: str) -> float:
        """统计每千字因果连词数量：于是、因此、所以、于是乎、从而"""
        if not content:
            return 0.0
        words = len(content)
        causal_markers = _re_q.findall(r'于是|因此|所以|于是乎|从而|导致|继而|随之|紧接着|结果|致使', content)
        return round(len(causal_markers) / max(words, 1) * 1000, 2)

    def _compute_conflict_intensity(self, content: str) -> float:
        """冲突烈度：识别冲突事件数量 * 平均强度，归一化到 0.0-1.0"""
        if not content:
            return 0.0
        # 冲突关键词 + 强度权重
        # 来源：基于网文语感经验值，待用户反馈/历史数据校准
        # 校准方向：可从已评分章节的 AI 评分与人工反馈中学习最优权重
        # P2 升级路径：用 TF-IDF 从高质量章节样本中自动学习关键词权重
        conflict_patterns = [
            (r'争吵|吵架|争执|对峙|搏斗|打斗|厮杀|激战', 0.9),
            (r'威胁|恐吓|逼迫|强迫|逼迫|施压', 0.8),
            (r'冲突|矛盾|分歧|不和|对立', 0.7),
            (r'质疑|质问|反驳|争辩|辩解', 0.6),
            (r'暗算|阴谋|陷害|背叛|出卖', 0.9),
            (r'竞争|比赛|较量|争夺', 0.5),
        ]
        total = 0.0
        for pattern, weight in conflict_patterns:
            matches = _re_q.findall(pattern, content)
            total += len(matches) * weight
        # 归一化：0-10个冲突事件映射到 0.0-1.0
        # 对数归一化：20 个冲突 ≈ 0.9，避免硬上限导致 >10 后饱和
        return round(math.log1p(total) / math.log1p(20), 3)

    def _compute_foreshadow_density(self, content: str) -> float:
        """伏笔密度：每千字新埋伏笔关键词数量"""
        if not content:
            return 0.0
        words = len(content)
        # 埋伏笔的常见语言特征
        foreshadow_markers = _re_q.findall(
            r'似乎|不由得|隐隐约|似乎.*想起|似乎.*察觉|隐约觉得|有种.*预感|莫名.*不安|似曾相识|恍惚间|总觉得.*不对劲', content
        )
        return round(len(foreshadow_markers) / max(words, 1) * 1000, 2)

    def _build_improvement_hints(self, suggestions: list) -> str:
        """构建ImprovementHints

        Args:
            self:
            suggestions:

        Returns:
            str
        """
        hints = []
        for s in suggestions:
            dim = s.split(':')[0] if ':' in s else s
            if dim == 'pacing':
                hints.append('注意节奏：开篇冲突前置，段落短小精悍')
            elif dim == 'dialogue':
                hints.append('增加有目的的对话，减少心理描写')
            elif dim == 'hook':
                hints.append('章末100字内必须有强钩子')
            elif dim == 'character_consistency':
                hints.append('检查角色行为和对话是否符合人设')
            elif dim == 'outline_adherence':
                hints.append('严格按章纲执行，不添加新剧情')
        return '\n'.join(hints[:3])


class QualityLoop:
    """质量闭环：评分 → 不合格 → 改进 → 重评分"""

    MAX_RETRIES = 3  # 与 PMQualityScorerV2.MAX_RETRIES 对齐；此前缺失导致 AttributeError

    def __init__(self, scorer: PMQualityScorerV2, memory=None):
        self.scorer = scorer
        self.memory = memory

    async def generate_with_loop(self, generate_fn, context: dict) -> dict:
        """生成WithLoop

        Args:
            self:
            generate_fn:
            context:

        Returns:
            dict
        """
        best_content = ''
        best_score = 0
        history = []

        for attempt in range(self.MAX_RETRIES):
            # 1. 生成
            content = await generate_fn(context)

            # 2. 评分
            result = self.scorer.score(content, context)
            total = result.total_score
            history.append({'attempt': attempt, 'score': total, 'passed': result.passed})

            if result.passed:
                logger.info(f'质量闭环: 第{attempt + 1}次通过, 评分{total:.0f}')
                if self.memory:
                    await self.memory.record('fusion', str(len(content)), str(total), score=total, scores_detail=result.scores)
                return {'content': content, 'score': total, 'attempts': attempt + 1, 'success': True}

            # 不合格：生成改进建议，注入 context
            if attempt < self.MAX_RETRIES - 1:
                context['improvement_hints'] = self.scorer._build_improvement_hints(result.suggestions)
                context['previous_attempt'] = attempt
                logger.info(f'质量闭环: 第{attempt + 1}次不合格({total:.0f}), 重试...')

            if total > best_score:
                best_content = content
                best_score = total

        return {
            'content': best_content,
            'score': best_score,
            'attempts': self.MAX_RETRIES,
            'success': False,
            'history': history,
            'warning': '超限重试，返回最佳结果',
        }
