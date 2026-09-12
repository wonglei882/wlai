"""
灵感模式·工具成功经验自动沉淀（P3 拆分自 skill_system 的 auto_skill 模块）

被以下位置懒导入（避免与 skill_system 形成模块级循环依赖）：
- skill_system.auto_summarize_from_pm_reply → _abstract_topic_from_pm / _classify_pm_reply
- skill_system._generate_skill_from_pm       → _build_constraint_skill / _build_general_skill / _build_technique_skill
- event_bus_listeners (经 inspiration_skills 转发) → auto_skill_from_tool_result

注：本模块模块级导入 skill_system 是安全的（skill_system 仅在函数内懒导入本模块）。
"""

import re
from datetime import datetime

import logging
from app.services.inspiration_sub.skill_system import InspirationSkillSystem
from app.services.inspiration_sub.skill_template import _make_skill_name

logger = logging.getLogger(__name__)


# =============================================================================
# 工具成功 → 经验沉淀（事件监听调用入口）
# =============================================================================
async def auto_skill_from_tool_result(
    user_id: str,
    user_input: str,
    tool_name: str,
    tool_params: dict,
    tool_result: dict,
) -> str | None:
    """工具执行成功后自动沉淀可复用经验为 skill。

    Args:
        user_id: 用户 ID
        user_input: 触发该工具的用户请求（如「第5章生成」）
        tool_name: 工具名（如 chapter_generation）
        tool_params: 调用参数
        tool_result: 工具返回结果 dict（含 success/message/data）

    Returns:
        沉淀成功的 skill 名；跳过或失败返回 None。全程非阻塞、异常安全。
    """
    try:
        if not _tool_succeeded(tool_result):
            return None
        pm_reply = _compose_tool_experience(tool_name, tool_result)
        if not pm_reply or len(pm_reply) < 80:
            return None
        return await InspirationSkillSystem.auto_summarize_from_pm_reply(user_id, user_input, pm_reply)
    except Exception as e:  # 非阻塞：失败仅记录，不向上抛
        logger.warning(f'auto_skill_from_tool_result 失败(非阻塞): {e}')
        return None


def _tool_succeeded(tool_result) -> bool:
    if not isinstance(tool_result, dict):
        return False
    return bool(tool_result.get('success') or tool_result.get('ok'))


def _compose_tool_experience(tool_name: str, tool_result: dict) -> str:
    """把工具成功结果拼成一段可供沉淀的 PM 经验文本（模拟 PM 回复）。"""
    message = str(tool_result.get('message') or '').strip()
    data = tool_result.get('data') or {}
    extra = ''
    if isinstance(data, dict):
        pairs = [f'{k}={v}' for k, v in data.items() if not str(k).lower().endswith('id')]
        if pairs:
            extra = '，产出 ' + '、'.join(str(p) for p in pairs[:5])
    text = f'本次使用 {tool_name} 工具成功完成了创作任务{extra}。{message}'
    return text.strip()


# =============================================================================
# PM 回复经验分类 / 主题抽象（skill_system 懒导入使用）
# =============================================================================
_CONSTRAINT_SIGNALS = ('禁止', '不要', '必须', '应该', '避免', '不能', '切勿', '切记', '避免出现')
_TECHNIQUE_SIGNALS = ('技巧', '方法', '步骤', '可以先', '尝试用', '建议采用')

_STOP_KEYWORDS = {
    '这个', '可以', '一个', '进行', '需要', '因为', '所以', '如果', '那么', '以及',
    '应该', '我们', '用户', '内容', '生成', '写作', '创作', '章节', '故事', '这样', '什么', '如何',
}


def _classify_pm_reply(pm_reply: str) -> str | None:
    """把 PM 回复分类为 约束 / 技法 / 经验；过短或无信号返回 None。"""
    if not pm_reply or len(pm_reply) < 80:
        return None
    if any(s in pm_reply for s in _CONSTRAINT_SIGNALS):
        return '约束'
    if any(s in pm_reply for s in _TECHNIQUE_SIGNALS):
        return '技法'
    return '经验'


def _abstract_topic_from_pm(user_input: str, pm_reply: str, category: str) -> str:
    """从用户输入与 PM 回复中抽象出普遍适用的技能主题（规则版，无需 LLM）。"""
    topic = (user_input or '').strip().rstrip('？?。.！! 　')
    if not topic:
        topic = f'{category}创作经验'
    keywords = _extract_keywords(pm_reply)
    if keywords and keywords[0] not in topic:
        topic = f'{topic}·{keywords[0]}'
    return topic[:30] or '创作经验'


def _extract_keywords(text: str, limit: int = 3) -> list[str]:
    """提取文本中的创作领域关键词（连续中文词，过滤停用词）。"""
    words = re.findall(r'[\u4e00-\u9fff]{2,6}', text)
    seen = set()
    out = []
    for w in words:
        if w in _STOP_KEYWORDS or len(w) < 2:
            continue
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= limit:
            break
    return out


# =============================================================================
# PM 经验类 Skill 正文模板（约束 / 技法 / 经验）
# =============================================================================
def _build_constraint_skill(topic: str, user_input: str, pm_reply: str) -> str:
    """构建「约束类」skill：把创作红线沉淀为可检索的规则。"""
    return (
        '---\n'
        f'name: {_make_skill_name(topic)}\n'
        f'description: 约束场景——创作「{topic}」时必须遵守的规则\n'
        '---\n\n'
        f'# {topic}\n\n'
        '## 触发条件\n'
        f'- 典型用户请求：{user_input[:60]}\n'
        '- 用户创作涉及该主题，且需要检查是否踩线时\n\n'
        '## 操作步骤\n'
        '1. 识别请求涉及的创作对象与场景\n'
        '2. 对照核心约束逐条检查当前内容\n'
        '3. 违反约束时立即指出，并给出修正建议\n\n'
        '## 核心约束\n'
        f'{_wrap_quote(pm_reply, 4)}\n\n'
        '## 可复用模式\n'
        '- 将每次创作的约束沉淀为结构化规则，供后续章节复用\n\n'
        '## 复用记录\n'
        f'- 首次生成：{datetime.now().strftime("%Y-%m-%d")}\n'
        f'  触发：「{user_input[:40]}」\n'
    )


def _build_technique_skill(topic: str, user_input: str, pm_reply: str) -> str:
    """构建「技法类」skill：把创作技巧沉淀为可复用的操作手法。"""
    return (
        '---\n'
        f'name: {_make_skill_name(topic)}\n'
        f'description: 技法场景——创作「{topic}」时可直接套用的技巧\n'
        '---\n\n'
        f'# {topic}\n\n'
        '## 触发条件\n'
        f'- 典型用户请求：{user_input[:60]}\n'
        '- 用户需要类似题材/场景的写法建议时\n\n'
        '## 操作步骤\n'
        '1. 定位请求对应的创作环节（如铺垫、对话、转折）\n'
        '2. 套用下列技法组织内容，注意与整体节奏匹配\n'
        '3. 检查技法落地效果，必要时微调\n\n'
        '## 技法要点\n'
        f'{_wrap_quote(pm_reply, 4)}\n\n'
        '## 可复用模式\n'
        '- 技法类经验可跨项目复用，复用 2 次后可晋升全局库\n\n'
        '## 复用记录\n'
        f'- 首次生成：{datetime.now().strftime("%Y-%m-%d")}\n'
        f'  触发：「{user_input[:40]}」\n'
    )


def _build_general_skill(topic: str, user_input: str, pm_reply: str) -> str:
    """构建「经验类」skill：把可复用的创作经验沉淀为通用模式。"""
    return (
        '---\n'
        f'name: {_make_skill_name(topic)}\n'
        f'description: 经验场景——创作「{topic}」时可直接参考的做法\n'
        '---\n\n'
        f'# {topic}\n\n'
        '## 触发条件\n'
        f'- 典型用户请求：{user_input[:60]}\n'
        '- 用户遇到同类创作问题时\n\n'
        '## 操作步骤\n'
        '1. 回顾该主题的历史做法\n'
        '2. 参考可复用模式，结合当前上下文落地\n'
        '3. 记录本次复用情况，积累经验\n\n'
        '## 可复用模式\n'
        f'{_wrap_quote(pm_reply, 4)}\n\n'
        '## 复用记录\n'
        f'- 首次生成：{datetime.now().strftime("%Y-%m-%d")}\n'
        f'  触发：「{user_input[:40]}」\n'
    )


def _wrap_quote(text: str, indent: int) -> str:
    """把多行文本统一缩进（Markdown 引用块展示）。"""
    prefix = ' ' * indent
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return '\n'.join(f'{prefix}- {l[:80]}' for l in lines) or f'{prefix}- （无具体内容）'
