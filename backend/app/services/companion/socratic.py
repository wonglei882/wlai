"""
维度 S · 苏格拉底的大脑 — 引导式提问，不直接给答案

核心入口：socratic_redirect_if_needed —— 供 pm_agent_decision.diagnose_and_fix
在「阶段 1 决策」之前调用。命中引导规则时返回 decision='guide' 的 result
（与现有 manual/skip 短路结果同形状），由用户逐步作答；未命中返回 None，
PM 主链路完全不受影响。

引导命中规则（全部满足才拦截）：
1. 功能开关 optional.companion 开启
2. 问题类型在白名单引导表内（真实巡检类型带 pm_agent_ 前缀，查表前自动归一化）
3. 严重度不是 critical（严重问题直接修复，不做教学）
4. 用户水平不是 expert（专家不需要被提问）
"""

from datetime import datetime

import logging

logger = logging.getLogger(__name__)


# =============================================================================
# 引导问题库：按 diag_type 组织的三级提问链（现象→原因→方案）
# =============================================================================
_GUIDABLE_TYPES: dict[str, dict] = {
    'character_consistency': {
        'topic': '角色行为一致性',
        'levels': [
            '这个场景里，角色哪处言行让你觉得和之前的形象不太一致？',
            '如果 TA 始终如一，此刻最可能的反应会是什么？',
            '你想让 TA 在这次冲突中发生怎样的变化，才让「不同」有了意义？',
        ],
    },
    'character_location_jump': {
        'topic': '角色位置跳变',
        'levels': [
            '这个角色上一场景结束时在哪里？本场景又从哪里开始？',
            '中间这段路（或时间）发生的事，读者需要看到吗？',
            '如果补一拍过渡，你希望读者注意到什么？',
        ],
    },
    'plot_logic': {
        'topic': '剧情逻辑',
        'levels': [
            '这条剧情线里，最让读者「咦？」的转折点是哪一处？',
            '如果按你设定的人物动机推演，这个转折站得住吗？',
            '怎样埋一个更早的因，让这个果顺理成章？',
        ],
    },
    'continuity': {
        'topic': '情节连续性',
        'levels': [
            '前后两段情节之间的「衔接缝」在哪里？',
            '读者在这里断掉的话，断在哪一步（信息/情感/时间）？',
            '用什么最小改动能把这条缝补上，同时留下余味？',
        ],
    },
    'style_consistency': {
        'topic': '文风一致',
        'levels': [
            '这一段和整体文风最「出戏」的是哪个词或哪句？',
            '你心目中这个故事的「统一声音」是什么样的？',
            '如果只保留一版，你会保留哪个写法？为什么？',
        ],
    },
    'world_rule_drift': {
        'topic': '世界观规则漂移',
        'levels': [
            '这次的设定用法，和之前确立的规则哪里有出入？',
            '你当初定这条规则，是为了支撑什么？',
            '是改掉这次用法，还是为它补一个更早的伏笔？',
        ],
    },
    'foreshadow_stale': {
        'topic': '伏笔过期',
        'levels': [
            '这条伏笔埋下去多久了？读者还会记得吗？',
            '它最迟要在哪个节点前回收，才不会让读者失望？',
            '你能设计哪一处「轻勾连」，让读者重新想起它？',
        ],
    },
    'pacing': {
        'topic': '叙事节奏',
        'levels': [
            '这一段的节奏，比前后是快了还是慢了？',
            '读者此刻的情绪诉求是什么——紧张、喘息，还是期待？',
            '你打算用哪一拍（加/减/调序）把节奏拉回读者需要的位置？',
        ],
    },
    'dialogue_quality': {
        'topic': '对话质量',
        'levels': [
            '这段对话，两个人真的在「听」对方吗？',
            '每句台词如果去掉，信息或情感会损失多少？',
            '哪句台词可以改成「动作+短句」，让它更像真人说话？',
        ],
    },
    'character_jump': {
        'topic': '角色位置跳变',
        'levels': [
            '这个角色上一场景结束时在哪里？本场景又从哪里开始？',
            '中间这段路（或时间）发生的事，读者需要看到吗？',
            '如果补一拍过渡，你希望读者注意到什么？',
        ],
    },
    'outline_drift': {
        'topic': '大纲漂移',
        'levels': [
            '正文已经偏离大纲，最先「脱轨」的是哪一处情节？',
            '这次偏离，是角色自己的选择，还是写作时的顺手为之？',
            '你更想让大纲跟随故事，还是让故事回到大纲？为什么？',
        ],
    },
    'paragraph_too_long': {
        'topic': '段落过长',
        'levels': [
            '这一长段里，读者最需要抓住的核心信息是哪一个？',
            '如果把段落按「一个焦点一层意思」拆开，哪里该起新段？',
            '拆分后哪一句适合单独成段，制造一点呼吸感？',
        ],
    },
}

_DEFAULT_CHAIN: dict = {
    'topic': '创作问题',
    'levels': [
        '你最先注意到这个问题的地方是哪里？',
        '如果顺着直觉再想一层，它可能由什么引起？',
        '你自己心里有没有一个「如果这样会更好」的方向？',
    ],
}

# 别名：真实巡检类型 pm_agent_world_drift 归一化为 world_drift，与 world_rule_drift 同链
_GUIDABLE_TYPES['world_drift'] = _GUIDABLE_TYPES['world_rule_drift']

# 严重度排除：critical 的问题直接修复，不做引导（枚举: critical / warning / info）
_NON_GUIDE_SEVERITIES = {'critical'}
# 专家级用户不需要引导
_NON_GUIDE_LEVELS = {'expert'}


# =============================================================================
# 引导规则判断
# =============================================================================
def _normalize_type(issue_type: str) -> str:
    """把真实巡检类型归一化为白名单 key（去除 pm_agent_ 前缀）。"""
    itype = (issue_type or '').strip()
    return itype[len('pm_agent_'):] if itype.startswith('pm_agent_') else itype


def resolve_chain(diag_type: str) -> dict | None:
    """按诊断类型取引导链（自动归一化 pm_agent_* 前缀）；不在白名单返回 None。"""
    return _GUIDABLE_TYPES.get(_normalize_type(diag_type))


def should_guide(
    diag_type: str,
    severity: str,
    experience_level: str = 'beginner',
    autonomy_level: str = '',
) -> bool:
    """引导命中判定（feature 开关在调用方另行校验）。"""
    if severity in _NON_GUIDE_SEVERITIES:
        return False
    if experience_level in _NON_GUIDE_LEVELS:
        return False
    return resolve_chain(diag_type) is not None


def build_socratic_chain(issue: dict, project_ctx: dict | None = None) -> dict:
    """生成三级提问链（纯规则，保证可用）。"""
    diag_type = issue.get('type', '')
    chain = resolve_chain(diag_type) or _DEFAULT_CHAIN
    brief = (issue.get('message') or '')[:120]
    return {
        'topic': chain['topic'],
        'issue_brief': brief,
        'levels': [{'step': i + 1, 'question': q} for i, q in enumerate(chain['levels'])],
        'mode': 'socratic',
    }


# =============================================================================
# 主入口：巡检链路引导拦截
# =============================================================================
async def socratic_redirect_if_needed(
    db,
    issue: dict,
    project_id: str,
    user_id: str,
    diag_type: str,
    severity: str,
) -> dict | None:
    """诊断链路引导拦截。命中返回 decision='guide' 的结果；未命中返回 None。"""
    # 1) 功能开关（companion 默认关闭，开启才介入）
    try:
        from app.services.pm.feature_config import is_pm_feature_enabled

        if not is_pm_feature_enabled('optional.companion'):
            return None
    except Exception as e:
        logger.warning('[companion] 功能开关读取失败，跳过引导: %s', e)
        return None

    # 2) 用户水平（无画像按 beginner 处理）
    level = 'beginner'
    try:
        from app.models.pm_user_profile import PMUserProfile
        from sqlalchemy import select

        r = await db.execute(select(PMUserProfile).where(PMUserProfile.user_id == user_id).limit(1))
        profile = r.scalar_one_or_none()
        if profile and profile.experience_level:
            level = profile.experience_level
    except Exception as e:
        logger.warning('[companion] 读取用户画像失败，按 beginner 处理: %s', e)

    # 3) 命中判定
    if not should_guide(diag_type, severity, level):
        return None

    # 4) 组装引导结果
    chain = build_socratic_chain(issue)
    logger.info('[companion] 苏格拉底引导命中: type=%s severity=%s level=%s', diag_type, severity, level)
    result = {
        'type': diag_type,
        'severity': severity,
        'decision': 'guide',
        'fix_action': '',
        'fix_result': 'guided',
        'fix_attempted': False,
        'verified': False,
        'verify_message': '已进入苏格拉底引导模式，等待用户回答问题',
        'decision_log_id': None,
        'guidance': {
            'mode': 'socratic',
            'topic': chain['topic'],
            'questions': [lvl['question'] for lvl in chain['levels']],
        },
    }

    # 5) 记录 guide 决策（与 manual 短路同构；失败不影响返回）
    try:
        from app.models.pm_decision_log import PMDecisionLog

        log = PMDecisionLog(
            project_id=project_id,
            user_id=user_id,
            diag_type=diag_type,
            severity=severity,
            original_message=(issue.get('message') or '')[:500],
            decision='guide',
            decision_reason='苏格拉底引导模式：问题可引导且用户水平允许',
            fix_action='',
            fix_result='guided',
            fix_attempted=False,
            verified=False,
            verify_message='等待用户回答引导问题',
            scan_round='',
        )
        db.add(log)
        await db.commit()
        result['decision_log_id'] = log.id
    except Exception as e:
        logger.warning('[companion] 记录 guide 决策失败(非阻塞): %s', e)
        try:
            await db.rollback()
        except Exception:
            pass

    return result


# =============================================================================
# API 辅助：根据用户回答生成引导反馈（可选 LLM，失败降级规则）
# =============================================================================
async def generate_socratic_reply(
    db,
    user_id: str,
    issue: dict,
    answer: str,
) -> str:
    """对用户某一问的回答给出原则性反馈（不直接给答案）。

    优先尝试 LLM 生成（若用户已配置 API）；失败降级为规则反馈。
    """
    chain = build_socratic_chain(issue)
    answer_text = (answer or '').strip()[:200]
    if len(answer_text) < 2:
        return '可以多说一点吗？你的感受本身就很关键。'

    # 尝试 LLM
    try:
        from app.services.companion import prompts
        from app.services.pm.pm_ai_client import get_pm_ai_client

        client = await get_pm_ai_client(user_id, db)
        if client is not None:
            scene = (issue.get('message') or '')[:100]
            prompt = prompts.render(
                'socratic_chain',
                scene=scene,
                issue=chain['topic'],
            )
            system = (
                '你是苏格拉底式的创作引导者。绝不直接给答案，'
                '只基于作者的作答给出一个更深入的问题或原则性提示。'
            )
            reply = await client.generate_text(system, prompt, temperature=0.7, max_tokens=200)
            if reply and reply.strip():
                return reply.strip()[:300]
    except Exception as e:
        logger.warning('[companion] LLM 引导反馈失败，降级规则: %s', e)

    # 规则降级：认可 + 再推进一步
    return (
        f'这个思考方向很好。基于你说的「{answer_text[:40]}」，'
        '不妨再问自己一层：如果这个答案成立，它对整个故事的影响是什么？'
    )
