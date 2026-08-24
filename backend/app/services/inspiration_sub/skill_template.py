"""
Skill 内容模板构建器（P3：从 auto_skill.py 拆分）

仅含纯模板函数，无 I/O/DB/logger 依赖。
"""

from datetime import datetime


# =============================================================================
# 共享工具（与 auto_skill.py 保持一致）
# =============================================================================
def _make_skill_name(topic: str) -> str:
    """将 topic 转换为合法的 skill 文件名（去除非法字符）。"""
    import re
    import hashlib

    clean = re.sub(r'[<>:"/\\|?*\s]', '', topic).strip()
    if not clean:
        clean = 'skill'
    if len(clean) > 30:
        clean = clean[:30]
    suffix = hashlib.md5(topic.encode(), usedforsecurity=False).hexdigest()[:6]
    return f'{clean}_{suffix}'


# =============================================================================
# P3: 工具模式 Skill 内容模板（结构化：步骤≥3 + 触发关键词 + 具体描述）
# =============================================================================
def _build_tool_pattern_skill(
    topic: str,
    category: str,
    user_input: str,
    tool_name: str,
    tool_params: dict,
    result_summary: str,
    obj_text: str,
    trigger_kw: str = '',
) -> str:
    """构建工具模式类 skill 的正文（P3: 结构化步骤+触发关键词+具体描述）。"""
    # 隐藏必填参数（去掉ID等长字段，保留关键参数）
    display_params = {k: (v[:30] + '...' if len(str(v)) > 30 else v) for k, v in tool_params.items() if k not in ('user_id', 'project_id')}
    params_text = ', '.join(f'{k}={v}' for k, v in display_params.items())

    # 触发关键词（结构化，用于检索匹配）
    # 仅当 trigger_kw 看起来有意义（长度≤6且不含无意义前缀）才加入，避免通用降级产生垃圾
    kw_list = []
    if trigger_kw and len(trigger_kw) <= 6 and not any(c in trigger_kw for c in '请第的查分'):
        kw_list.append(trigger_kw)
    # 从工具名 + 用户输入补充关键词
    if 'character' in tool_name:
        kw_list.extend(['角色状态', '一致性'])
    elif 'foreshadow' in tool_name:
        kw_list.extend(['伏笔', '埋设'])
    elif 'outline' in tool_name:
        kw_list.extend(['章纲', '序列'])
    elif 'chapter' in tool_name:
        kw_list.extend(['章节', '生成'])
    elif 'volume' in tool_name:
        kw_list.extend(['分卷', '卷纲'])
    # 去重
    seen = set()
    kw_list = [k for k in kw_list if not (k in seen or seen.add(k))]
    kw_text = '、'.join(kw_list) if kw_list else '（见典型请求）'

    return (
        '---\n'
        f'name: {_make_skill_name(topic)}\n'
        f'description: {category}场景——用户需对「{topic}」执行PM工具时直接复用\n'
        '---\n\n'
        f'# {topic}\n\n'
        '## 触发条件\n'
        f'- 关键词：{kw_text}（命中任一即触发）\n'
        f'- 典型用户请求：{user_input[:60]}\n\n'
        '## 使用工具\n'
        f'[TOOL:{tool_name}|{params_text}]\n\n'
        '## 执行步骤\n'
        f'1. 确认操作对象：从用户请求提取参数（目标：{obj_text}）\n'
        f'2. 调用工具：{tool_name}，必填参数 {params_text}\n'
        '3. 处理结果：检查 success 字段；成功则记录本次复用，失败则向用户说明原因\n\n'
        '## 预期结果\n'
        f'{result_summary}\n\n'
        '## 适用场景\n'
        f'- 用户提到类似「{trigger_kw or user_input[:20]}」需求时 → 直接调用，无需询问\n\n'
        '## 复用记录\n'
        f'- 首次生成：{datetime.now().strftime("%Y-%m-%d")}\n'
        f'  触发：「{user_input[:40]}」\n\n'
    )
