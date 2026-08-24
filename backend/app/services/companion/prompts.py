"""
companion 提示词模板库（补齐「提示词工坊」模板层缺口）

分场景模板 + 统一渲染入口 render(name, **kw)：
- socratic_chain   维度 S：苏格拉底提问引导
- tutor_feedback   维度 T：家教分层反馈
- knowledge_inject 维度 E：知识注入
- secretary_brief  维度 P：秘书简报

所有模板为纯 Python f-string 风格（.format），无外部依赖；
为后续提示词工坊服务化（按 instance 管理模板）预留位置。
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模板正文
# ---------------------------------------------------------------------------
SOCRATIC_CHAIN_TMPL = """作为苏格拉底式的创作引导者，你绝不直接给出答案，而是通过提问帮助作者自己发现问题。

当前创作场景：{scene}
已确认的问题：{issue}

请按下面三个层次引导作者（每个层次至少一个问题，语气温和而好奇）：
1. 现象确认：让作者描述他观察到的现象或感受
2. 原因探询：引导作者追溯可能的深层原因
3. 方案自省：启发作者自己提出候选方案

注意：
- 一次只推进一层，不要一次性抛出所有问题
- 问题要具体、可回答，避免空泛
- 不评价对错，只做镜子"""

TUTOR_FEEDBACK_TMPL = """以一位耐心家教的口吻，针对作者的创作问题进行分层反馈。

作者当前水平：{experience_level}
问题：{issue}
错误次数：{attempt_count}

反馈要求：
- 语气：{tone}
- 先共情一句，再讲清{principle}，最后给{steps}。
- {example_instruction}
- 结尾加一句鼓励，不要长篇大论。"""

KNOWLEDGE_INJECT_TMPL = """以下是与当前创作相关的知识参考（来自创作百科与作者的经验技能库）：

{knowledge}

请自然地把其中适用的内容融入回答，不要生硬引用，也不要提到「知识库」这类词。"""

SECRETARY_BRIEF_TMPL = """你是作者最贴心的私人创作秘书，为他生成一份简短、温暖的每日创作简报。

称呼：{name}
语气偏好：{tone}
当日创作进展：{progress}
待办提醒：{reminders}
可选小贴士：{tips}

简报要求：
- 开头按时段问候
- 2~4 句话，简洁不啰嗦
- 先讲好消息，再提提醒
- 结尾一句暖心的鼓励"""

TEMPLATES: dict[str, str] = {
    'socratic_chain': SOCRATIC_CHAIN_TMPL,
    'tutor_feedback': TUTOR_FEEDBACK_TMPL,
    'knowledge_inject': KNOWLEDGE_INJECT_TMPL,
    'secretary_brief': SECRETARY_BRIEF_TMPL,
}


def render(name: str, **kwargs) -> str:
    """渲染指定模板；缺失关键字时保留原样并告警（不抛错）。"""
    tmpl = TEMPLATES.get(name)
    if tmpl is None:
        raise KeyError(f'未知模板: {name}')
    try:
        return tmpl.format(**kwargs)
    except (KeyError, IndexError) as e:
        logger.warning('模板 %s 渲染缺少关键字: %s（返回原模板）', name, e)
        return tmpl


def available_templates() -> list[str]:
    """列出所有模板名（工坊层可据此管理）。"""
    return sorted(TEMPLATES)
