"""章节进度趋势分析（独立部署实现）。

基于章节质量得分序列做轻量趋势判断（前段均值 vs 后段均值）。
主系统中该能力由更大数据量 + AI 模型提供，独立部署下用统计近似。
"""
import logging

logger = logging.getLogger(__name__)

# 判定为上升/下降的均值差阈值（质量分通常为 0~100 区间）
_DIFF_THRESHOLD = 5.0
# 最少样本数：少于该值不判定趋势
_MIN_SAMPLES = 3


def detect_progress_trend(scores: list[float]) -> dict:
    """根据近 N 章质量得分序列判断创作趋势。

    返回结构：
        {
            "trend": "上升|下降|平稳",
            "confidence": float,   # 0.0~1.0，随样本量增大而升高
            "advice": str,
        }
    """
    clean = [float(s) for s in (scores or []) if s is not None]
    n = len(clean)
    if n == 0:
        return {'trend': '平稳', 'confidence': 0.0, 'advice': '暂无质量数据，暂不判断趋势'}
    if n < _MIN_SAMPLES:
        return {'trend': '平稳', 'confidence': 0.0, 'advice': '样本不足，暂不判断趋势'}

    half = n // 2
    first_avg = sum(clean[:half]) / half
    last_avg = sum(clean[half:]) / (n - half)
    diff = last_avg - first_avg

    if diff > _DIFF_THRESHOLD:
        trend = '上升'
        advice = '近期章节质量持续走高，可适当加大剧情推进力度与冲突密度。'
    elif diff < -_DIFF_THRESHOLD:
        trend = '下降'
        advice = '近期章节质量下滑，建议检查节奏、冲突密度与文风一致性。'
    else:
        trend = '平稳'
        advice = '章节质量总体平稳，保持当前创作节奏。'

    # 样本越多置信度越高，封顶 1.0
    confidence = min(1.0, n / 10.0)
    return {
        'trend': trend,
        'confidence': round(confidence, 2),
        'advice': advice,
    }
