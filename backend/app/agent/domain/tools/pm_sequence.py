"""PM 序列生成上下文工具组：build_context / record_outcome / get_chapter_summary

供 PM agent 在链式生成中构建结构化上下文、记录结局、查询已生成序列。
也供 _chain_helpers.py 以普通 async function 方式程序化调用。
"""

from app.agent.core.command_registry import ToolRegistry, ToolDefinition, RiskLevel
from app.services.json_helper import safe_int, safe_json_loads
import logging
from pathlib import Path
import asyncio

logger = logging.getLogger(__name__)


# ==================== 情绪值 -> 文字描述映射 ====================
EMOTION_MAP = {
    -5: '【情绪基调】极度绝望——主角一切挣扎均告失败，希望彻底破灭。',
    -4: '【情绪基调】深重悲痛——常有角色死亡、梦想破碎，压抑到令人窒息。',
    -3: '【情绪基调】高度紧张——主角处于被动挨打的困境，压迫感与危机四伏。',
    -2: '【情绪基调】焦虑低沉——面临困境但尚未崩溃，前途未卜压力渐增。',
    -1: '【情绪基调】轻微紧张——一丝隐忧与不确定感潜入，氛围略偏压抑。',
    0: '【情绪基调】中性平静——叙事平稳，不过度渲染情绪，正文自然推进。',
    +1: '【情绪基调】略带回暖——一丝希望初现，略有转机但尚不足以乐观。',
    +2: '【情绪基调】轻快希望——柳暗花明、曙光初现，主角找到方向或获得小胜。',
    +3: '【情绪基调】愉悦振奋——主角顺风顺水、志得意满，胜利与收获的快感。',
    +4: '【情绪基调】兴奋高燃——热血沸腾、全力爆发，绝地反击或碾压对手。',
    +5: '【情绪基调】极度高燃——碾压一切的极致爽感，热血沸腾、打脸极致。',
}


# ==================== 数据库工具函数（可程序化调用） ====================


async def pm_build_sequence_context(
    chapter_id: str,
    seq_index: int,
    seq_label: str,
    core_task: str,
    target_words: int,
    emotion_value: int,
    techniques: list,
    prev_sequence_ending: str,
    final_hook: str,
    db,
    chapter_context: dict = None,
) -> str:
    """构建序列生成的结构化上下文约束"""
    from sqlalchemy import select
    from app.models.chapter import Chapter
    from app.models.project import Project
    from app.models.foreshadow import Foreshadow

    ch_r = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = ch_r.scalar_one_or_none()
    if not chapter:
        return '【错误】章节不存在'

    proj_r = await db.execute(select(Project).where(Project.id == chapter.project_id))
    proj_r.scalar_one_or_none()  # 保留查询副作用，结果未使用

    # 读取已有序列结局
    prev_outcomes = []
    try:
        ep = safe_json_loads(chapter.expansion_plan, {})
        prev_outcomes = ep.get('sequence_outcomes', [])
    except Exception:
        prev_outcomes = []

    # 读取待回收伏笔
    fs_r = await db.execute(
        select(Foreshadow).where(
            Foreshadow.project_id == chapter.project_id,
            Foreshadow.status.in_(['pending', 'planted']),
        )
    )
    foreshadows = list(fs_r.scalars().all())

    # 构建约束清单

    # 1. 衔接起点
    prev_block = ''
    if prev_sequence_ending:
        prev_block = '1. 衔接起点：承接上一序列结尾——' + prev_sequence_ending + '\n   开头必须自然承接上述结尾，禁止重复已写过的场景和情绪。\n'
    elif seq_index == 0:
        prev_block = '1. 衔接起点：这是本章第一个序列，开头须自然承接上一章结尾。\n'

    # 2. 核心任务
    core_block = '2. 本序列核心任务：' + core_task + '\n'

    # 3. 收尾约束
    LABEL_ORDER = ['铺垫', '触发', '试探', '中点反转', '绝境', '破局', '高潮', '收尾']
    next_block = ''
    if seq_index < 7:
        next_label = LABEL_ORDER[seq_index + 1] if seq_index + 1 < len(LABEL_ORDER) else ''
        next_block = '3. 本序列结尾状态：必须推进到' + core_task + '的实现结果，为下一序列（' + next_label + '）做好准备。\n'
    else:
        next_block = '3. 结尾约束：本序列是收尾，必须自然引入结尾钩子——' + final_hook + '。\n'

    # 4. 情绪基调
    emotion_block = '4. ' + EMOTION_MAP.get(emotion_value, '【情绪基调】中性平静——叙事平稳推进。') + '\n'

    # 5. 伏笔约束
    foreshadow_block = ''
    if foreshadows:
        fs_lines = []
        for f in foreshadows[:5]:
            fs_lines.append('  - \u300c' + f.title + '\u300d：' + (f.content or '')[:80] + '（状态：' + f.status + '）')
        foreshadow_block = '5. 伏笔约束——本章待回收/续埋的伏笔：\n' + '\n'.join(fs_lines) + '\n' + '   在序列剧情推进中，自然提及或推进上述伏笔。\n'

    # 6. 角色约束（从 chapter_context 取，不依赖 Project 模型）
    role_block = ''
    p1 = (chapter_context or {}).get('p1_important') or {}
    if p1.get('ooc_constraints'):
        role_block = '6. 角色约束：' + p1['ooc_constraints'][:300] + '\n'

    # 7. 禁止事项
    forbid_block = (
        '7. 禁止事项：\n  - 禁止使用插说句式（双破折号、括号补充、\u201c也就是\u201d等）\n  - 禁止引入剧情中没有的新角色\n  - 禁止跨越核心任务范围\n'
    )

    # 8. 已生成序列摘要
    summary_block = ''
    if prev_outcomes:
        summary_lines = []
        for po in prev_outcomes:
            idx = po.get('index', -1) + 1
            label = po.get('label', '?')
            ending = (po.get('actual_ending') or '')[:60]
            summary_lines.append('  序列' + str(idx) + '（' + label + '）：' + ending + '...')
        summary_block = '\n8. 本章已生成序列回顾：\n' + '\n'.join(summary_lines) + '\n'

    # 技法推荐
    tech_block = ''
    if techniques:
        tech_block = '\n【推荐写作技法】\n' + '\u3001'.join(techniques) + '\n'

    # ② 延伸：读质量陷阱skill经验，追加为禁止约束
    try:
        from app.services.inspiration_skills import _search_skills_by_context

        # 关键序列（3/5/6/7）优先查质量陷阱skill
        priority_types = ['quality_', '质量陷阱', '插说', '截断']
        skill_hints = []
        for kw in priority_types:
            hits = await _search_skills_by_context(
                context={'keyword': kw, 'seq_index': seq_index, 'chapter_context': chapter_context},
                db=db,
                user_id='global',
                threshold=0.35,
            )
            if hits:
                skill_hints.extend(hits[:1])  # 每个类型最多1条
                break  # 命中即停
        if skill_hints:
            skill_warnings = []
            for h in skill_hints[:2]:
                name = h.get('name', '')
                desc = (h.get('content', '') or '')[:100]
                skill_warnings.append(f'【质量陷阱】{name}：{desc}')
            if skill_warnings:
                forbid_block += '\n⚠️ 质量经验约束（历史教训）：\n  ' + '\n  '.join(skill_warnings) + '\n'
    except Exception as e:
        logger.warning(f'[pm_build_context] 技能警告扫描失败: {e}')

    context = (
        '【约束清单】\n'
        + prev_block
        + core_block
        + next_block
        + emotion_block
        + foreshadow_block
        + role_block
        + forbid_block
        + summary_block
        + tech_block
    )

    return context


async def pm_record_sequence_outcome(
    chapter_id: str,
    seq_index: int,
    seq_label: str,
    actual_ending: str,
    db,
    foreshadow_hints: list = None,
    quality_score: int = None,
    consistency_issues: list = None,
) -> dict:
    """记录序列生成后的实际结局"""
    from sqlalchemy import select, update
    from app.models.chapter import Chapter
    import json

    ch_r = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = ch_r.scalar_one_or_none()
    if not chapter:
        return {'recorded': False, 'error': '\u7ae0\u8282\u4e0d\u5b58\u5728'}

    try:
        ep = safe_json_loads(chapter.expansion_plan, {})
    except Exception:
        ep = {}

    outcomes = ep.get('sequence_outcomes', [])

    found = False
    for o in outcomes:
        if o.get('index') == seq_index:
            o['label'] = seq_label
            o['actual_ending'] = actual_ending
            if quality_score is not None:
                o['quality_score'] = quality_score
            if consistency_issues is not None:
                o['consistency_issues'] = consistency_issues
            found = True
            break
    if not found:
        outcomes.append(
            {
                'index': seq_index,
                'label': seq_label,
                'actual_ending': actual_ending,
                'quality_score': quality_score,
                'consistency_issues': consistency_issues or [],
            }
        )

    ep['sequence_outcomes'] = outcomes

    stmt = update(Chapter).where(Chapter.id == chapter_id).values(expansion_plan=json.dumps(ep, ensure_ascii=False))
    await db.execute(stmt)
    await db.commit()

    return {
        'recorded': True,
        'total_outcomes': len(outcomes),
        'latest_ending': actual_ending[:60],
    }


async def pm_get_chapter_summary(
    chapter_id: str,
    db,
) -> dict:
    """获取本章各序列的已生成结局"""
    from sqlalchemy import select
    from app.models.chapter import Chapter
    from app.models.foreshadow import Foreshadow

    ch_r = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = ch_r.scalar_one_or_none()
    if not chapter:
        return {'chapter_number': 0, 'sequence_outcomes': [], 'remaining_sequences': [], 'pending_foreshadows': []}

    try:
        ep = safe_json_loads(chapter.expansion_plan, {})
    except Exception:
        ep = {}

    outcomes = ep.get('sequence_outcomes', [])
    completed_indices = {o.get('index') for o in outcomes if o.get('actual_ending')}

    all_labels = [
        '\u94fa\u57ab',
        '\u89e6\u53d1',
        '\u8bd5\u63a2',
        '\u4e2d\u70b9\u53cd\u8f6c',
        '\u7edd\u5883',
        '\u7834\u5c40',
        '\u9ad8\u6f6e',
        '\u6536\u5c3e',
    ]
    remaining = [{'index': i, 'label': all_labels[i]} for i in range(len(all_labels)) if i not in completed_indices]

    fs_r = await db.execute(
        select(Foreshadow)
        .where(
            Foreshadow.project_id == chapter.project_id,
            Foreshadow.status.in_(['pending', 'planted']),
        )
        .limit(10)
    )
    fs_list = [f.title for f in fs_r.scalars().all()]

    return {
        'chapter_number': chapter.chapter_number,
        'sequence_outcomes': outcomes,
        'remaining_sequences': remaining,
        'pending_foreshadows': fs_list,
    }


# =============================================================================
# 方案1：生成前诊断上下文
# =============================================================================
async def pm_build_diagnostic_context(project_id: str, db) -> str:
    """生成注入到序列约束的诊断提醒（只注入有问题的部分）。

    调用链：
      - PMConsistencyState  → 最近3章一致性问题
      - _review_counts.json → 高频问题类型
      - Foreshadow          → 逾期伏笔
    """
    import json
    import os
    from sqlalchemy import select, func
    from app.models.pm_consistency_state import PMConsistencyState
    from app.models.foreshadow import Foreshadow
    from app.models.chapter import Chapter

    parts = []

    # 1. 一致性高频问题（读持久化计数）
    try:
        review_path = '/app/data/inspiration_skills/_review_counts.json'
        if os.path.exists(review_path):
            _raw = await asyncio.to_thread(Path(review_path).read_text, encoding='utf-8')
            counts = json.loads(_raw)
            if counts:
                top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:3]
                if top and top[0][1] >= 2:
                    issues_str = '、'.join([f'「{k}」出现{str(v)}次' for k, v in top])
                    parts.append(f'⚠️ 高频问题：{issues_str}，本章注意避免')
    except Exception as e:
        logger.warning(f'[pm_build_diagnostic_context] 高频问题扫描失败: {e}')

    # 2. 逾期伏笔（age > 5章）
    try:
        ch_r = await db.execute(select(func.max(Chapter.chapter_number)).where(Chapter.project_id == project_id))
        latest_ch = ch_r.scalar() or 0

        fs_r = await db.execute(
            select(Foreshadow).where(
                Foreshadow.project_id == project_id,
                Foreshadow.status.in_(['pending', 'planted']),
            )
        )
        overdue = []
        for f in fs_r.scalars().all():
            planted_ch = getattr(f, 'chapter_number', None) or 0
            age = latest_ch - planted_ch
            if age >= 5:
                overdue.append((f.title, age))
        if overdue:
            titles = '、'.join([f'「{t}」已{age}章' for t, age in overdue[:3]])
            parts.append(f'⚠️ 伏笔逾期：{titles}，请自然提及')
    except Exception as e:
        logger.warning(f'[pm_build_diagnostic_context] 伏笔逾期扫描失败: {e}')

    # 3. 最近一致性问题（从 PMConsistencyState 读）
    try:
        cs_r = await db.execute(
            select(PMConsistencyState).where(PMConsistencyState.project_id == project_id).order_by(PMConsistencyState.updated_at.desc()).limit(5)
        )
        recent = list(cs_r.scalars().all())
        if recent:
            issues = [getattr(r, 'issue_type', '') or getattr(r, 'issue_summary', '') for r in recent]
            issues = [i for i in issues if i][:3]
            if issues:
                parts.append(f'⚠️ 最近问题：{"、".join(issues)}')
    except Exception as e:
        logger.warning(f'[pm_build_diagnostic_context] 一致性问题扫描失败: {e}')

    if not parts:
        return ''

    return '\n【PM诊断提醒】\n' + '\n'.join(parts) + '\n'


# =============================================================================
# 方案2：生成中快速审查
# =============================================================================
_EMOTION_KEYWORDS = {
    -5: ['绝望', '无力', '崩塌', '毁灭', '绝望'],
    -4: ['悲痛', '丧', '死', '破碎', '心碎'],
    -3: ['紧张', '危机', '压迫', '困境', '危机四伏'],
    -2: ['焦虑', '低沉', '压力', '迷茫'],
    -1: ['隐忧', '不确定', '压抑'],
    0: [],
    1: ['希望', '转机', '回暖'],
    2: ['曙光', '方向', '小胜', '柳暗花明'],
    3: ['顺风', '得意', '收获', '胜利'],
    4: ['热血', '爆发', '绝地反击', '碾压'],
    5: ['极致', '碾压', '打脸', '高潮'],
}

# 侧面描写模式：动作/神态/环境烘托，表达情绪但不用直白情感词。
# 只要命中任一模式，即视为情绪基调已有体现（用户偏好动作等侧面描写）。
_EMOTION_SHOW_PATTERNS = [
    # 动作描写（手/身体）
    r'攥紧|握紧|捏紧|握拳|指节发白|青筋|骨节|抖|颤|咬牙|咬唇|抿唇|攥|握拳',
    r'僵住|顿住|怔住|愣住|踉跄|后退|跌坐|瘫软|瘫坐|扑通|倒吸',
    # 神态描写（脸/眼/眉）
    r'眼神|目光|眼底|瞳孔|眼眶|泛红|发红|湿润|水光|视线',
    r'脸色|面|眉|嘴角|唇角|抽动|笑意|苦笑|惨笑|冷笑|唇线|紧绷',
    r'垂头|低头|抬眼|抬头|别过脸|转过脸|垂下|埋首',
    # 环境烘托（气氛/景物）
    r'风|雨|雷|电|阴|暗|影|灯光|烛火|寂静|沉默|无声|死寂|空气|气氛',
    # 声音/对话语气
    r'声音发颤|颤抖着说|嘶哑|沙哑|哽咽|低声|吼|喊|咆哮|呢喃|喃喃',
]


async def pm_quick_sequence_check(
    content: str,
    seq_index: int,
    seq_label: str,
    target_words: int,
    emotion_value: int,
    core_task: str,
    chapter_context: dict = None,
) -> dict:
    """快速审查序列质量（<100ms），返回是否通过及问题列表。

    触发策略：
      - seq_index ∈ {3,5,6,7}（中点反转/绝境/破局/高潮）→ 全量检查
      - 其他序列 → 只检查截断和长度
    """
    import re

    issues = []
    wc = len(content)
    word_count = wc  # 近似字数

    # 1. 长度检查（所有序列）
    tol = 150 if seq_index in (3, 5, 6, 7) else 200
    if not (target_words - tol <= word_count <= target_words + tol):
        issues.append(f'字数偏差过大：{word_count}字（目标{target_words}±{tol}）')

    # 2. 截断检测（所有序列）
    stripped = content.rstrip()
    last_char = stripped[-1] if stripped else ''
    if last_char in '，、：：' or stripped.endswith('，\n'):
        issues.append('在句子中间截断（禁止截断）')

    # 3. 全量检查（关键序列）
    if seq_index in (3, 5, 6, 7):
        # 3a. 禁止词检测
        forbid_patterns = [
            r'——',
            r'—{2,}',
            r'（[^{}]*）',
            r'，也就是',
            r'\([^(]*\)',
            r'也就是[^，。]*[,。]',
        ]
        for pat in forbid_patterns:
            if re.search(pat, content):
                issues.append('使用了插说句式（禁止）')
                break

        # 3b. 情绪基调契合（直白情感词 OR 动作/神态/环境侧面描写）
        emotion_words = _EMOTION_KEYWORDS.get(emotion_value, [])
        if emotion_words:
            matched = sum(1 for w in emotion_words if w in content)
            shown = sum(1 for p in _EMOTION_SHOW_PATTERNS if re.search(p, content))
            if matched == 0 and shown == 0 and abs(emotion_value) >= 3:
                issues.append(f'情绪基调偏离（期望{emotion_value}级情绪，未检测到情感词或动作/神态/环境侧面描写）')

        # 3c. 核心任务契合（分段匹配：角色 + 核心动作任一命中即可）
        if core_task and core_task.strip():
            import re as _re

            # 提取角色名（2-4字连续中文，常是人名）
            characters = _re.findall(
                r'[\u4e00-\u9fff]{2,4}(?=(?:试探|找|问|说|告诉|给|递|拿|问|追|质问|逼|威胁|发现|揭露|揭穿|对抗|挑战))',
                core_task,
            )
            characters += _re.findall(r'(?:对|与|和)([\u4e00-\u9fff]{2,4})', core_task)
            characters = list(dict.fromkeys(characters))  # 去重保留顺序
            # 提取核心动作词（≥2字）
            action_words = _re.findall(r'[\u4e00-\u9fff]{2,6}(?:试探|发现|揭露|揭穿|对抗|挑战|威胁|逼迫|追问|对峙)', core_task)
            action_words += _re.findall(r'(?:被|让|使)([\u4e00-\u9fff]{2,4})', core_task)
            # 整个任务句作为兜底关键词（取前20字）
            full_phrase = core_task[:20]

            char_ok = any(c in content for c in characters[:4]) if characters else False
            act_ok = any(a in content for a in action_words[:4]) if action_words else False
            full_ok = full_phrase in content
            if not (char_ok or act_ok or full_ok):
                issues.append(f'核心任务「{core_task[:30]}」未在内容中体现')

    passed = len(issues) == 0
    score = max(0, 100 - len(issues) * 15)

    return {
        'passed': passed,
        'score': score,
        'issues': issues,
        'word_count': word_count,
    }


# =============================================================================
# 方案3：质量数据沉淀到 skill
# =============================================================================
async def _deposit_quality_pattern_skill(
    project_id: str,
    issue_type: str,
    example_bad: str,
    fix_suggestion: str,
    db,
) -> dict:
    """将高频质量问题沉淀为 skill 经验，下次生成自动避开。

    写入 global skill（跨项目共享）。
    """
    import os
    from app.services.inspiration_skills import (
        InspirationSkillSystem,
        _upsert_skill_embedding,
    )

    skill_name = f'质量陷阱-{issue_type}'
    skill_id = f'quality_{issue_type[:8]}'
    content = f"""# {skill_name}

## 问题类型
{issue_type}

## 典型案例
{example_bad[:500] if example_bad else '（无）'}

## 修复建议
{fix_suggestion}

## 触发条件
在序列生成时，若当前章节属于以下类型，自动注入此约束：
- 中点反转（seq_index=3）
- 绝境（seq_index=5）
- 高潮（seq_index=6）

## 生成时提醒
生成前请回顾「{skill_name}」案例，避免重复同类问题。
"""

    try:
        global_dir = InspirationSkillSystem._global_skills_dir()
        os.makedirs(global_dir, exist_ok=True)
        skill_path = os.path.join(global_dir, f'{skill_name}.md')
        with open(skill_path, 'w', encoding='utf-8') as f:
            f.write(content)
        _upsert_skill_embedding('global', skill_name, content, source='global')
        return {'deposited': True, 'skill_id': skill_id}
    except Exception as e:
        return {'deposited': False, 'error': str(e)}


def register_pm_sequence_tools(registry: ToolRegistry) -> None:
    """注册PM序列Tools

    Args:
        registry:

    Returns:
        None
    """

    async def _handle_build_context(params: dict, db):
        """处理构建上下文

        Args:
            params:
            db:

        Returns:
            None
        """
        seq_index = safe_int(params.get('sequence_index', 0), 0)
        return [
            await pm_build_sequence_context(
                chapter_id=params.get('chapter_id', ''),
                seq_index=seq_index,
                seq_label=params.get('sequence_label', ''),
                core_task=params.get('core_task', ''),
                target_words=safe_int(params.get('target_words', 300), 300),
                emotion_value=safe_int(params.get('emotion_value', 0), 0),
                techniques=params.get('techniques', []),
                prev_sequence_ending=params.get('prev_sequence_ending', ''),
                final_hook=params.get('final_hook', ''),
                db=db,
            )
        ]

    registry.register(
        ToolDefinition(
            name='pm_build_sequence_context',
            description='为指定序列（1-8）构建结构化上下文约束清单，含伏笔、角色、情绪、衔接点等信息',
            params_schema={
                'chapter_id': 'str: \u7ae0\u8282UUID',
                'sequence_index': 'int: \u5e8f\u5217\u7d22\u5f15(0-7)',
                'sequence_label': 'str: \u5e8f\u5217\u6807\u7b7e',
                'core_task': 'str: \u6838\u5fc3\u4efb\u52a1\u63cf\u8ff0',
                'target_words': 'int: \u76ee\u6807\u5b57\u6570',
                'emotion_value': 'int: \u60c5\u7eea\u503c(-5~+5)',
                'techniques': 'list[str]: \u63a8\u8350\u7684\u5199\u4f5c\u6280\u6cd5\u5217\u8868',
                'prev_sequence_ending': 'str: \u4e0a\u4e00\u5e8f\u5217\u7684\u5b9e\u9645\u7ed3\u5c3e',
                'final_hook': 'str: \u672c\u7ae0\u7ed3\u5c3e\u94a9\u5b50\uff08S8\u9700\u8981\uff09',
            },
            required_params=['chapter_id', 'sequence_index'],
            param_types={'chapter_id': 'str'},
            handler=_handle_build_context,
            risk_level=RiskLevel.LOW,
        )
    )

    async def _handle_record_outcome(params: dict, db):
        """处理RecordOutcome

        Args:
            params:
            db:

        Returns:
            None
        """
        result = await pm_record_sequence_outcome(
            chapter_id=params.get('chapter_id', ''),
            seq_index=safe_int(params.get('sequence_index', 0), 0),
            seq_label=params.get('sequence_label', ''),
            actual_ending=params.get('actual_ending', ''),
            db=db,
            foreshadow_hints=params.get('foreshadow_hints'),
        )
        if result.get('recorded'):
            return ['\u5e8f\u5217' + str(params.get('sequence_index', '?')) + '\u7ed3\u5c40\u5df2\u8bb0\u5f55']
        return ['\u8bb0\u5f55\u5931\u8d25: ' + result.get('error', '\u672a\u77e5\u9519\u8bef')]

    registry.register(
        ToolDefinition(
            name='pm_record_sequence_outcome',
            description='记录序列生成后的实际结局，更新伏笔状态',
            params_schema={
                'chapter_id': 'str: \u7ae0\u8282UUID',
                'sequence_index': 'int: \u5e8f\u5217\u7d22\u5f15(0-7)',
                'sequence_label': 'str: \u5e8f\u5217\u6807\u7b7e',
                'actual_ending': 'str: \u751f\u6210\u540e\u7684\u5b9e\u9645\u7ed3\u5c3e\u6587\u672c',
                'foreshadow_hints': 'list[str]: \u53ef\u9009\uff0c\u547d\u4e2d/\u63a8\u8fdb\u7684\u4f0f\u7b14\u5217\u8868',
            },
            required_params=['chapter_id', 'sequence_index', 'actual_ending'],
            param_types={'chapter_id': 'str'},
            handler=_handle_record_outcome,
            risk_level=RiskLevel.LOW,
        )
    )

    async def _handle_get_summary(params: dict, db):
        """处理获取Summary

        Args:
            params:
            db:

        Returns:
            None
        """
        result = await pm_get_chapter_summary(
            chapter_id=params.get('chapter_id', ''),
            db=db,
        )
        lines = ['\u7b2c' + str(result['chapter_number']) + '\u7ae0 \u5e8f\u5217\u751f\u6210\u6982\u51b5']
        for o in result.get('sequence_outcomes', []):
            ending = (o.get('actual_ending') or '')[:50]
            lines.append('  S' + str(o['index'] + 1) + '(' + o['label'] + '): ' + ending + '...')
        for r in result.get('remaining_sequences', []):
            lines.append('  S' + str(r['index'] + 1) + '(' + r['label'] + '): \u5f85\u751f\u6210')
        if result.get('pending_foreshadows'):
            lines.append('\u5f85\u56de\u6536\u4f0f\u7b14: ' + ', '.join(result['pending_foreshadows'][:5]))
        return lines

    registry.register(
        ToolDefinition(
            name='pm_get_chapter_summary',
            description='获取本章各序列的已生成结局、剩余序列、待回收伏笔',
            params_schema={
                'chapter_id': 'str: \u7ae0\u8282UUID',
            },
            required_params=['chapter_id'],
            param_types={'chapter_id': 'str'},
            handler=_handle_get_summary,
            risk_level=RiskLevel.LOW,
        )
    )
