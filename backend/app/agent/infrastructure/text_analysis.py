"""中文文本分析工具 — 基于 jieba 分词，jieba 不可用时降级为 regex 方案"""

import re
from collections import Counter

# 条件导入：jieba 不可用时降级
try:
    import jieba

    _JIEBA_AVAILABLE = True
except ImportError:
    jieba = None
    _JIEBA_AVAILABLE = False

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
    '她们',
    '已经',
    '开始',
    '知道',
    '觉得',
    '这样',
    '那样',
    '还是',
    '只是',
    '不过',
    '当然',
    '这么',
    '那么',
    '而且',
    '或者',
    '一直',
    '以后',
    '之前',
    '时候',
    '东西',
    '事情',
    '地方',
    '样子',
    '感觉',
    '一点',
    '不会',
    '可能',
    '应该',
}


def _regex_words(text: str) -> list[str]:
    """jieba 不可用时的降级方案：纯 regex 提取中文词"""
    return [w for w in re.findall(r'[\u4e00-\u9fff]{2,}', text) if w not in _STOP_WORDS]


def extract_keywords(text: str, top_n: int = 20) -> list[tuple[str, int]]:
    """从文本提取关键词（jieba分词+词频）

    优于旧 regex r'[\u4e00-\u9fff]{2,}' 方案：
    - 正确切分复合词（"陆沉" vs "陆沉从考场走出来时"）
    - 自动识别新词（人名、地名）
    - 过滤停用词

    jieba 不可用时降级为 regex 方案（功能降级但不崩溃）。

    Returns:
        [(word, count), ...] 按频次降序
    """
    if not text:
        return []
    words = [w for w in jieba.lcut(text) if len(w) >= 2 and w not in _STOP_WORDS] if _JIEBA_AVAILABLE else _regex_words(text)
    return Counter(words).most_common(top_n)


def extract_named_entities(text: str) -> dict[str, list[str]]:
    """提取命名实体（人名、地名、机构名）"""
    result = {'person': [], 'location': [], 'organization': []}
    if not text:
        return result

    if _JIEBA_AVAILABLE:
        import jieba.posseg as pseg

        words = pseg.lcut(text)
        for w, flag in words:
            if len(w) < 2:
                continue
            if flag == 'nr' and w not in result['person']:
                result['person'].append(w)
            elif flag == 'ns' and w not in result['location']:
                result['location'].append(w)
            elif flag == 'nt' and w not in result['organization']:
                result['organization'].append(w)
    # jieba 不可用时降级为空（regex 提取人名地名精度不足）
    return result


def analyze_writing_style(text: str) -> dict[str, any]:
    """分析写作风格指标

    Returns:
        {
            "word_count": 总词数,
            "unique_words": 不同词数,
            "vocabulary_richness": 词汇丰富度 (unique/total),
            "avg_word_len": 平均词长,
            "dialogue_ratio": 对白占比,
            "narration_ratio": 叙述占比,
            "top_keywords": 高频词列表,
            "emotion_words": 情感词数,
        }
    """
    if not text:
        return {}
    words = [w for w in jieba.lcut(text) if len(w) >= 1] if _JIEBA_AVAILABLE else [w for w in re.findall(r'[\u4e00-\u9fff]{2,}', text)]

    # 对白检测（中文引号\u201c\u201d + ASCII引号 + 单引号 + 直角引号\u300c\u300d）
    dialogues = re.findall(r'[\u201c\u201d"\'""""\u300c\u300d]([^\u201c\u201d"\'""""\u300c\u300d]*)[\u201c\u201d"\'""""\u300c\u300d]', text)
    dialogue_chars = sum(len(d) for d in dialogues)
    total_chars = len(text.replace('\n', '').replace(' ', ''))
    dialogue_ratio = dialogue_chars / total_chars if total_chars > 0 else 0

    # 情感词（简化词典）
    emotion_pos = {'开心', '高兴', '快乐', '喜欢', '爱', '幸福', '兴奋', '温暖', '欣慰', '满足'}
    emotion_neg = {'难过', '伤心', '痛苦', '害怕', '恐惧', '愤怒', '生气', '失望', '沮丧', '绝望'}
    emotion_words = sum(1 for w in words if w in emotion_pos or w in emotion_neg)

    # 词汇丰富度
    unique = len(set(w for w in words if len(w) >= 2))
    total = len(words)
    richness = unique / total if total > 0 else 0

    # 平均词长
    avg_len = sum(len(w) for w in words) / len(words) if words else 0

    return {
        'word_count': len(words),
        'unique_words': unique,
        'vocabulary_richness': round(richness, 3),
        'avg_word_len': round(avg_len, 2),
        'dialogue_ratio': round(dialogue_ratio, 3),
        'narration_ratio': round(1 - dialogue_ratio, 3),
        'top_keywords': extract_keywords(text, 10),
        'emotion_word_count': emotion_words,
    }


def get_chapter_word_profile(text: str) -> str:
    """生成章节词云摘要（供 AI 参考）"""
    keywords = extract_keywords(text, 30)
    if not keywords:
        return '（内容过短，无法分析）'
    lines = ['高频词（jieba分词）：' if _JIEBA_AVAILABLE else '高频词（regex降级）：']
    for word, count in keywords:
        bar = '█' * min(count, 10)
        lines.append(f'  {word} {bar} ({count})')
    return '\n'.join(lines)
