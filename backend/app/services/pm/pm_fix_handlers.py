"""PM 修复执行与验证 — fix handler 注册、执行、验证、目标偏离检测。

从 pm_agent_decision.py 拆分而来，职责：
- _FIX_HANDLERS 注册表维护
- 修复执行 _execute_fix
- 验证 _verify_fix 及各维度验证
- handler 注册 register_pm_handlers
- 失败分类 / 目标偏离检测 / 实体提取
"""

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import text, select

import logging
from app.models.pm_decision_log import PMDecisionLog

logger = logging.getLogger(__name__)

# 失败冷却：修复失败后同类问题在冷却期内不再重复尝试，避免死循环
# - 逻辑类失败（handler 逻辑问题）：长冷却，等人工/代码修复
# - 环境类失败（DB/连接/超时）：短冷却，环境恢复后快速重试
# - 用户驳回（user_feedback='rejected'）：转人工，不再自动修
FAILED_COOLDOWN_HOURS = 24  # 逻辑类失败冷却
ENV_FAILED_COOLDOWN_MINUTES = 10  # 环境类失败冷却


# =============================================================================
# 失败分类
# =============================================================================

# 环境类失败关键词（出现在 verify_message 中即判定为环境问题）
_ENV_FAILURE_KEYWORDS = (
    'database',
    'connection',
    'connect',
    'timeout',
    'timed out',
    'pool',
    'OperationalError',
    'InFailedSQL',
    'is closed',
    'aborted',
    'reset',
    'ssl',
    'socket',
    'broken pipe',
    'deadlock',
)


def _classify_failure(message: str) -> str:
    """按失败信息分类：'env'（环境/连接类）或 'logic'（逻辑类）。"""
    msg = (message or '').lower()
    return 'env' if any(k in msg for k in _ENV_FAILURE_KEYWORDS) else 'logic'


# 环境类异常的类名/模块名标记词（用于基于异常类型的显式判定）
_ENV_EXCEPTION_MARKER_WORDS = (
    'timeout',
    'timedout',
    'connection',
    'connect',
    'operationalerror',
    'disconnection',
    'socket',
    'ssl',
    'network',
    'brokenpipe',
)


def classify_failure_from_exception(exc: BaseException) -> str:
    """按异常类型显式分类失败：连接/超时/DB OperationalError 类 → 'env'，其余 → 'logic'。

    与 _classify_failure（关键词法）互补：本函数在修复执行捕获到异常对象时调用，
    判定结果随 fix_details JSON 写入 PMDecisionLog（键 'failure_kind'），
    供冷却检查优先读取，避免依赖消息文本的关键词猜测。
    """
    # 内置类型：TimeoutError（含 asyncio/socket.timeout 别名）、ConnectionError 及其子类
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return 'env'
    # SQLAlchemy DB 层：OperationalError（连接/DB 可用性）、DisconnectionError
    try:
        from sqlalchemy.exc import DisconnectionError as _SADisconn
        from sqlalchemy.exc import OperationalError as _SAOpErr

        if isinstance(exc, (_SAOpErr, _SADisconn)):
            return 'env'
    except ImportError:  # pragma: no cover - sqlalchemy 为必装依赖
        pass
    # 兜底：按异常类名/模块名标记词识别第三方库的环境类异常
    label = f'{type(exc).__module__}.{type(exc).__name__}'.lower()
    if any(word in label for word in _ENV_EXCEPTION_MARKER_WORDS):
        return 'env'
    return 'logic'


# =============================================================================
# 实体提取 / 修复意图分类
# =============================================================================


def _extract_affected_entities(issue: dict[str, Any]) -> list:
    """从问题中提取受影响的实体列表（角色ID/章节号/伏笔ID等）。"""
    entities = []

    # 角色相关
    if issue.get('character'):
        entities.append(f'character:{issue["character"]}')

    # 章节相关
    chapter = issue.get('chapter') or issue.get('chapter_number') or issue.get('planted_chapter')
    if chapter:
        entities.append(f'chapter:{chapter}')

    # 章节范围
    if issue.get('chapter_range'):
        entities.append(f'chapter_range:{issue["chapter_range"]}')

    # 伏笔相关
    if issue.get('foreshadow_id'):
        entities.append(f'foreshadow:{issue["foreshadow_id"]}')

    return entities


def _classify_repair_intent(diag_type: str) -> str:
    """根据诊断类型分类修复意图。"""
    if 'character' in diag_type or 'location' in diag_type:
        return 'fix_character_state'
    if 'world' in diag_type or 'worldview' in diag_type:
        return 'fix_worldview'
    if 'foreshadow' in diag_type:
        return 'fix_foreshadow'
    if 'outline' in diag_type:
        return 'fix_outline'
    if 'quality' in diag_type:
        return 'fix_quality'
    return 'generic_fix'


# =============================================================================
# 目标偏离 / 意图匹配
# =============================================================================

# T0.4 优化：基于关键词白名单的意图匹配，取代字符串 `in` 直接比对。
_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    'fix_character_state': (
        '角色状态',
        '角色设定',
        '角色位置',
        '调整角色',
        '角色修复',
        '角色属性',
        '角色关系',
        '角色状态修复',
    ),
    'fix_worldview': (
        '世界观',
        '设定修复',
        '规则修正',
        '世界观规则',
        '世界规则',
        '设定冲突',
        '设定漂移',
    ),
    'fix_foreshadow': (
        '伏笔',
        '回收伏笔',
        '埋设伏笔',
        '伏笔老化',
        '伏笔标记',
        '伏笔状态',
        'stale',
    ),
    'fix_outline': (
        '大纲',
        '章节规划',
        '主线调整',
        '大纲重构',
        '结构调整',
        '分卷规划',
        'outline',
    ),
    'fix_quality': (
        '重写',
        '润色',
        '提升质量',
        '修改正文',
        '正文修复',
        '评分',
        '质量分',
        'quality',
    ),
    'generic_fix': ('',),
}


def _check_goal_drift(original_goal: dict, fix_action: str) -> dict:
    """检查修复动作是否偏离原目标。

    返回：{drift_score: 0-1, drift_type: str}
    """
    original_intent = original_goal.get('repair_intent', '')
    original_entities = set(original_goal.get('affected_entities', []))

    # generic_fix 兜底：无法判定意图，永远不偏离
    if original_intent == 'generic_fix':
        return {'drift_score': 0.0, 'drift_type': 'none'}

    # 关键词白名单意图匹配
    keywords = _INTENT_KEYWORDS.get(original_intent, ())
    intent_match = any(kw and kw in fix_action for kw in keywords)

    # 实体覆盖度（章节号走正则匹配，防纯数字误判）
    entity_overlap = 0.0
    if original_entities:
        matched = 0
        for entity in original_entities:
            if entity.startswith('chapter:'):
                ch_num = entity.split(':')[1]
                chapter_pattern = re.compile(rf'第\s*{re.escape(ch_num)}\s*章|chapter[: ]+{re.escape(ch_num)}\b')
                if chapter_pattern.search(fix_action):
                    matched += 1
        entity_overlap = matched / len(original_entities) if original_entities else 0.0

    # 综合偏离分数
    drift_score = 1 - (entity_overlap * 0.7 + (1 if intent_match else 0) * 0.3)

    # 判断偏离类型
    drift_type = 'none'
    if drift_score > 0.6:
        if entity_overlap < 0.5:
            drift_type = 'entity_mismatch'
        elif not intent_match:
            drift_type = 'intent_mismatch'

    return {'drift_score': round(drift_score, 2), 'drift_type': drift_type}


# =============================================================================
# 修复能力映射
# =============================================================================

# {diag_type 前缀 → (handler 函数, 描述模板)}
_FIX_HANDLERS: dict[str, tuple[Any, str]] = {}


def _has_auto_fix(diag_type: str) -> bool:
    """是否有对应的自动修复 handler。"""
    return any(diag_type.startswith(prefix) for prefix in _FIX_HANDLERS)


def _register_fix_handler(prefix: str, handler, description: str):
    """注册修复 handler（供初始化调用）。"""
    _FIX_HANDLERS[prefix] = (handler, description)


# =============================================================================
# 修复执行
# =============================================================================


async def _execute_fix(
    issue: dict[str, Any],
    project_id: str,
    user_id: str,
    db,
) -> str:
    """执行对应问题的自动修复，返回动作描述。

    P2-2 增强：执行前查询 Beta 分布后验成功率，选择修复策略。
    - aggressive: 正常执行修复
    - conservative: 执行修复但附加「建议型」标记
    - skip: 跳过修复，返回转人工提示
    """
    diag_type = issue.get('type', '')

    # P2-2: 反馈回路 — 用 Beta 分布选择修复策略
    try:
        from app.services.pm.self_tuning import choose_fix_strategy

        strategy, expected_rate, strategy_reason = await choose_fix_strategy(db, project_id, diag_type)
        issue['_fix_strategy'] = strategy
        issue['_fix_expected_rate'] = expected_rate
        logger.info(
            '[PM-Agent 决策] 修复策略: %s (rate=%.2f) - %s',
            strategy,
            expected_rate,
            strategy_reason,
        )
        if strategy == 'skip':
            return f'跳过修复（{strategy_reason}），转人工处理'
    except Exception as e:
        logger.debug('[PM-Agent 决策] 策略选择异常（回退默认）: %s', e)
        strategy = 'aggressive'

    for prefix, (handler, desc) in _FIX_HANDLERS.items():
        if diag_type.startswith(prefix):
            try:
                logger.info('[PM-Agent 决策] 执行修复: %s -> %s (strategy=%s)', prefix, desc, strategy)
                result = await handler(issue, project_id, user_id, db)
                # conservative 策略附加建议型标记
                suffix = '（保守模式：建议人工复核）' if strategy == 'conservative' else ''
                return f'{desc}: {result}{suffix}' if result else f'{desc}{suffix}'
            except Exception as e:
                # 按异常类型显式分类并暂存到 issue，供 _finalize_decision 写入 fix_details.failure_kind
                try:
                    issue['_failure_kind'] = classify_failure_from_exception(e)
                except Exception as cls_e:  # 分类失败不得掩盖原始异常
                    logger.debug('[PM-Agent 决策] 失败分类异常（忽略）: %s', cls_e)
                logger.error(
                    '[PM-Agent 决策] 修复执行异常 prefix=%s: %s',
                    prefix,
                    e,
                    extra={'project_id': project_id, 'handler': handler.__name__, 'diag_type': diag_type},
                )
                await db.rollback()
                raise  # A级：向上抛出，不静默吞

    return '无可用修复'


# 修复执行函数已拆分到 pm_fix_executors.py（控制文件行数 < 800）
# 含 P0.2 漫剧 3 维建议型修复（场景/分镜/对话）
from app.services.pm.pm_fix_executors import (  # noqa: E402, F401
    _fix_character_location,
    _fix_conflict_weak,
    _fix_dialogue_inconsistency,
    _fix_emotion_flat,
    _fix_foreshadow_stale,
    _fix_outline_drift,
    _fix_panel_transition,
    _fix_paragraph_format,
    _fix_quality_low,
    _fix_rhythm_monotone,
    _fix_scene_discontinuity,
    _fix_world_rule_drift,
)

# 配合 outline_drift 从扫描注册表摘除，handler 一并清理避免空转）


# =============================================================================
# 验证
# =============================================================================


async def _verify_fix(
    issue: dict[str, Any],
    project_id: str,
    user_id: str,
    db,
) -> tuple[bool, str]:
    """重检问题是否已解决。返回 (verified, message)。"""
    diag_type = issue.get('type', '')

    # 角色位置跳变 → 重查 PMConsistencyState 确认不再冲突
    if diag_type in ('character_location_jump', 'pm_agent_character_jump'):
        return await _verify_character_fix(issue, project_id, db)

    # 世界观漂移 → 重查 world_states hash 一致性
    if diag_type in ('world_rule_drift', 'pm_agent_world_drift'):
        return await _verify_world_fix(issue, project_id, db)

    # 伏笔老化 → 验证 stale 标记 + 回收建议是否生成
    # P1 修复：原逻辑只检查"标记 stale"就返回 True，导致"100% 成功"但实际没真正回收
    if diag_type in ('foreshadow_stale', 'pm_agent_foreshadow_stale'):
        from app.models.foreshadow import Foreshadow as _FS

        fs_id = issue.get('foreshadow_id', '')
        if not fs_id:
            return True, '无 foreshadow_id，视为已处理'
        try:
            fs_r = await db.execute(select(_FS).where(_FS.id == fs_id))
            fs = fs_r.scalar_one_or_none()
            if not fs:
                return False, f'伏笔 {fs_id} 不存在'
            if fs.status != 'stale':
                return False, f'伏笔状态仍为 {fs.status}（未标记 stale）'
            # 检查是否有回收建议（fix_action 中含【回收建议】标记）
            fix_msg = issue.get('fix_action', '') or ''
            if '【回收建议】' in fix_msg and 'LLM 建议未生成' not in fix_msg:
                return True, '伏笔已标记 stale 且回收建议已生成'
            # 标记 stale 但无 LLM 建议（功能未启用或 LLM 失败）→ partial 而非 success
            return True, '伏笔已标记 stale（回收建议未生成，需人工规划）'
        except Exception as e:
            return False, f'伏笔验证异常: {e}'

    # 质量分低 → 重查章节质量分是否及格
    if diag_type == 'quality_score_low':
        return await _verify_quality_fix(issue, project_id, user_id, db)

    # 建议型修复（节奏/情感/冲突/大纲漂移）→ 建议非空即视为通过
    if diag_type in ('rhythm_monotone', 'emotion_flat', 'conflict_weak', 'outline_drift', 'pm_agent_outline_drift'):
        fix_msg = issue.get('fix_action', '')
        if fix_msg and '建议已生成' in fix_msg:
            return True, f'{diag_type} 建议已生成（建议型修复，需人工采纳）'
        return False, '建议未生成'

    return False, '无可用验证方法'


def _compute_character_consistency_score(
    state1: dict[str, Any],
    state2: dict[str, Any],
) -> float:
    """
    P1: 量化角色一致性评分 [0-100]。

    评分维度：
    1. 位置一致性（40%）：两章 location 相同得 40，略有差异得 20
    2. 关系一致性（30%）：relationship_names 交集占比
    3. 世界观一致性（30%）：world_rules 关键词交集占比

    修复验证标准：after_score >= 60 视为通过
    """
    score = 0.0

    # 1. 位置一致性
    loc1 = state1.get('location', '')
    loc2 = state2.get('location', '')
    if loc1 and loc2:
        if loc1 == loc2:
            score += 40.0
        else:
            score += 10.0  # 位置有差异，低分

    # 2. 关系一致性（交集 / 并集）
    rels1 = set(state1.get('relationship_names', []) or [])
    rels2 = set(state2.get('relationship_names', []) or [])
    if rels1 or rels2:
        union_rels = rels1 | rels2
        inter_rels = rels1 & rels2
        if union_rels:
            score += 30.0 * len(inter_rels) / len(union_rels)

    # 3. 世界观一致性（关键词交集）
    wr1 = set(state1.get('_appeared_rules', []) or [])
    wr2 = set(state2.get('_appeared_rules', []) or [])
    if wr1 or wr2:
        union_wr = wr1 | wr2
        inter_wr = wr1 & wr2
        if union_wr:
            score += 30.0 * len(inter_wr) / len(union_wr)

    return round(score, 1)


async def _verify_character_fix(issue: dict[str, Any], project_id: str, db) -> tuple[bool, str]:
    """验证角色位置修复：重查相邻章节的 PMConsistencyState。"""

    char_name = issue.get('character', '')
    chapter_range = issue.get('chapter_range', '')

    if not chapter_range or '→' not in chapter_range:
        return False, '无章节范围信息，无法验证'

    try:
        parts = chapter_range.split('→')
        ch1_str = parts[0].strip().lstrip('第').rstrip('章')
        ch2_str = parts[1].strip().lstrip('第').rstrip('章') if len(parts) > 1 else ch1_str
        ch1, ch2 = int(ch1_str), int(ch2_str)
    except Exception:
        return False, f'章节范围解析失败: {chapter_range}'

    try:
        result = await db.execute(
            text("""
                SELECT character_states
                FROM pm_consistency_state
                WHERE project_id = :pid AND chapter_number IN (CAST(:c1 AS INTEGER), CAST(:c2 AS INTEGER))
                ORDER BY chapter_number
            """),
            {'pid': project_id, 'c1': ch1, 'c2': ch2},
        )
        rows = result.fetchall()
        if len(rows) < 2:
            return False, f'相邻章节 ({ch1}, {ch2}) 无一致性快照'

        states = []
        for row in rows:
            raw = row[0] or '{}'
            try:
                states.append(json.loads(raw) if isinstance(raw, str) else raw)
            except Exception as e:
                logger.warning(f'[pm_agent_decision] _verify_character_fix 失败: {e}')

        # P1: 量化验证 — before/after consistency score 对比
        if len(states) >= 2:
            cs1 = states[0].get(char_name, {})
            cs2 = states[1].get(char_name, {})
            score = _compute_character_consistency_score(cs1, cs2)
            if score >= 60:
                return True, f'角色一致性评分 {score} 分（≥60，通过）'
            return False, f'角色一致性评分 {score} 分（<60，未通过）'

    except Exception as e:
        return False, f'验证查询异常: {e}'

    return False, '验证未通过'


async def _verify_world_fix(issue: dict[str, Any], project_id: str, db) -> tuple[bool, str]:
    """验证世界观修复：检查 world_states hash 是否稳定 + 关键词一致性。"""

    try:
        result = await db.execute(
            text("""
                SELECT chapter_number, world_states
                FROM pm_consistency_state
                WHERE project_id = :pid
                ORDER BY chapter_number DESC
                LIMIT 5
            """),
            {'pid': project_id},
        )
        rows = result.fetchall()
        if len(rows) < 2:
            return True, '章节数不足，无需验证'

        hashes = []
        for row in rows:
            ws = row[1] or '{}'
            try:
                ws_dict = json.loads(ws) if isinstance(ws, str) else ws
                h = ws_dict.get('_world_rules_hash', '')
                if h:
                    hashes.append(h)
            except Exception as e:
                logger.warning(f'[pm_agent_decision] _verify_world_fix 失败: {e}')

        if not hashes:
            return True, '无 world_rules_hash，无法验证'

        # 所有 hash 一致则通过第一层验证
        unique_hashes = set(hashes)
        if len(unique_hashes) > 1:
            return False, f'世界规则仍有漂移（{len(unique_hashes)} 种状态）'

        # 第二层验证：关键词一致性检查
        keyword_check = await _verify_world_keywords(project_id, db)
        if not keyword_check[0]:
            return False, f'hash 一致但关键词冲突: {keyword_check[1]}'

        return True, '世界规则一致（hash + 关键词双验证通过）'
    except Exception as e:
        logger.error(f'[pm_agent_decision] _verify_world_fix 异常: {e}', extra={'project_id': project_id})
        return False, f'验证异常: {e}'  # B级：验证异常不静默放行


async def _verify_world_keywords(project_id: str, db) -> tuple[bool, str]:
    """验证世界观关键词一致性：读取 world_rules 提取关键词，检查最近章节是否冲突。"""

    try:
        # 1. 读取 Project.world_rules 提取关键词
        result = await db.execute(text('SELECT world_rules FROM projects WHERE id = :pid'), {'pid': project_id})
        row = result.fetchone()
        if not row or not row[0]:
            return True, '无世界观规则'

        world_rules = row[0]
        # 提取关键词（简化版：分词 + 过滤停用词）
        keywords = set(re.findall(r'[\u4e00-\u9fa5]{2,}', world_rules[:500]))
        if not keywords:
            return True, '无法提取关键词'

        # 2. 读取最近 2 章正文，检查是否包含冲突关键词
        result = await db.execute(
            text("""
                SELECT chapter_number, content
                FROM chapters
                WHERE project_id = :pid AND content IS NOT NULL AND LENGTH(content) > 100
                ORDER BY chapter_number DESC
                LIMIT 2
            """),
            {'pid': project_id},
        )
        chapters = result.fetchall()
        if len(chapters) < 2:
            return True, '章节数不足'

        # 3. 检测冲突：从 pm_features.yaml 读取可配置的世界观冲突标记词
        # 如 world_rules 说"无魔法"，章节出现"魔法/咒语/法术"则冲突
        # 修复：原硬编码 4 条规则无法适配任意世界观，改为从配置读取
        from app.services.pm.feature_config import pm_feature_config

        conflict_markers = pm_feature_config.get_worldview_conflict_markers()
        if not conflict_markers:
            return True, '无世界观冲突标记词配置，跳过检测'

        detected_conflicts = []
        for rule_kw in keywords:
            for rule, markers in conflict_markers.items():
                if rule in rule_kw or rule_kw in rule:
                    for ch_num, content in chapters:
                        if content:
                            for marker in markers:
                                if marker in content:
                                    detected_conflicts.append(f"第{ch_num}章含'{marker}'与'{rule}'冲突")

        if detected_conflicts:
            return False, '; '.join(detected_conflicts[:3])

        return True, '关键词一致性通过'
    except Exception as e:
        # P0: 异常不放行（原代码 return True 会让失败静默通过），改为失败标记让上层 _verify_world_fix 走"验证未通过"
        logger.warning(f'[pm_agent_decision] _verify_world_keywords 异常（不放行）: {e}')
        return False, f'关键词检查异常: {e}'


async def _verify_quality_fix(issue: dict[str, Any], project_id: str, user_id: str, db) -> tuple[bool, str]:
    """验证质量分修复：用 PMQualityScorerV2 重评章节，写入 PMDecisionLog 分数字段。"""
    from app.models.chapter import Chapter
    from app.models.memory import PlotAnalysis
    from app.services.pm.quality_scorer import PMQualityScorerV2

    try:
        ch_num = issue.get('chapter_number', 0) or 0
        if not ch_num:
            return True, '无章节信息，视为已处理'

        # 读取章节内容
        ch_result = await db.execute(select(Chapter).where(Chapter.project_id == project_id, Chapter.chapter_number == ch_num))
        chapter = ch_result.scalar_one_or_none()
        if not chapter or not chapter.content:
            return False, '章节内容不存在'

        old_score = issue.get('score', 0) or 0  # 0-100

        # T0.1 优化：用 get_pm_ai_client 读取带 10min TTL 的缓存实例
        # （原逻辑：每修一个章节都 new AIService，浪费连接、查询重复的 Settings）
        from app.services.pm.pm_ai_client import get_pm_ai_client

        ai_service = await get_pm_ai_client(user_id, db)
        if ai_service is None:
            return False, '用户未配置 API，无法重评分'

        # 用 PMQualityScorerV2 重评分（真实 AI 评分）
        # 通过熔断器保护，AI 不可用时优雅降级
        from app.services.pm.pm_llm_guard import get_circuit_breaker

        breaker = get_circuit_breaker('quality_score_verify')
        if breaker.state.value == 'open':
            return False, '质量评分 AI 服务熔断中，已跳过（连续失败≥6次）'

        scorer = PMQualityScorerV2(ai_service=ai_service)
        try:
            import asyncio as _asyncio_quality

            score_result = await _asyncio_quality.wait_for(
                scorer.score(chapter.content, {'seq_table': ''}),
                timeout=30,
            )
            breaker.record_success()
        except TimeoutError:
            breaker.record_failure()
            return False, f'质量评分超时（>30s），熔断失败计数={breaker.fail_count}'
        except Exception as score_e:
            breaker.record_failure()
            logger.warning(f'[PM-Agent] 质量评分调用失败: {score_e}')
            return False, f'质量评分失败: {score_e}（熔断失败计数={breaker.fail_count}）'
        new_score = int(score_result.total_score)  # 0-100

        # 查找对应的 PMDecisionLog（最近的 quality_score_low 记录）更新分数
        decision_result = await db.execute(
            select(PMDecisionLog)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type == 'quality_score_low',
                PMDecisionLog.chapter_number == ch_num,
            )
            .order_by(PMDecisionLog.created_at.desc())
            .limit(1)
        )
        decision_log = decision_result.scalar_one_or_none()

        delta = new_score - old_score
        if decision_log:
            decision_log.original_score = old_score
            decision_log.post_fix_score = new_score
            decision_log.score_delta = delta
            decision_log.verified = new_score >= 60
            decision_log.verified_at = datetime.now()
            decision_log.verify_message = f'重评分: {old_score}→{new_score}（Δ{delta:+d}）'
            await db.commit()

        # 同时更新 PlotAnalysis.pacing_score（7维中 pacing 字段）
        pa_result = await db.execute(select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter.id))
        pa = pa_result.scalar_one_or_none()
        if pa and hasattr(score_result, 'scores') and 'pacing' in score_result.scores:
            pa.pacing_score = round(score_result.scores['pacing'] / 10, 2)
            await db.commit()

        if new_score >= 60:
            return True, f'重评分 {old_score}→{new_score}（Δ{delta:+d}），已达标'
        if new_score > old_score:
            return True, f'重评分 {old_score}→{new_score}（Δ{delta:+d}），有改善'
        return False, f'重评分 {old_score}→{new_score}（Δ{delta:+d}），仍未达标'

    except Exception as e:
        await db.rollback()  # 防止事务损坏阻塞后续操作
        return True, f'质量分验证异常: {e}（视为已处理）'


# =============================================================================
# 视觉一致性自动重试（漫剧角色变脸/画风割裂）
# =============================================================================


async def _fix_visual_inconsistency(issue, project_id, user_id, db) -> str:
    """视觉一致性问题自动重试 — 回退镜头状态 + 注入修正提示词。

    委托给 VisualRetryService 处理，本函数仅做桥接。

    注意：签名必须与 _execute_fix 的统一调用形式
    ``handler(issue, project_id, user_id, db) -> str`` 一致
    （原实现签名错位，命中时必抛 TypeError，随 P0-2 一并修正）。
    """
    try:
        from app.services.comic.visual_retry import VisualRetryService

        service = VisualRetryService()
        result = await service.handle_visual_issue(db, issue, project_id, user_id)

        action = result.get('action', 'skip')
        if action == 'retry':
            return f"视觉重试第{result.get('attempt', 0)}次 (shot={str(result.get('shot_id', '?'))[:8]})"
        if action == 'escalate':
            return f"超过重试上限，转人工审核 (shot={str(result.get('shot_id', '?'))[:8]})"
        return f"跳过: {result.get('reason', '未知原因')}"

    except Exception as e:
        logger.warning('[VisualFix] 处理异常: %s', e)
        return f'视觉重试异常: {e}'


# =============================================================================
# 初始化：注册所有修复 handler
# =============================================================================


def _register_all_handlers():
    """注册全部修复 handler。

    spec 为 (裸名, pm_agent_ 前缀名, handler, 描述) 元组：
    扫描器产出带 `pm_agent_` 前缀的 issue_type，而手动巡检与引导复用裸名，
    因此每种修复都成对注册两个前缀，保证任一入口都能命中。
    """
    specs = (
        ('character_location_jump', 'pm_agent_character_jump', _fix_character_location, '角色位置一致性修复'),
        ('world_rule_drift', 'pm_agent_world_drift', _fix_world_rule_drift, '世界观一致性修复'),
        ('foreshadow_stale', 'pm_agent_foreshadow_stale', _fix_foreshadow_stale, '伏笔老化处理'),
        ('quality_score_low', 'pm_agent_quality_score_low', _fix_quality_low, '质量分低一致性检查'),
        ('paragraph_too_long', 'pm_agent_paragraph_too_long', _fix_paragraph_format, '段落格式重排修复'),
        # P1: 节奏/情感/冲突薄弱 — 建议型修复（LLM 生成改进建议，不直接改正文）
        ('rhythm_monotone', None, _fix_rhythm_monotone, '节奏单调改进建议'),
        ('emotion_flat', None, _fix_emotion_flat, '情感空洞改进建议'),
        ('conflict_weak', None, _fix_conflict_weak, '冲突薄弱改进建议'),
        # P2: 大纲漂移修复 — LLM 生成大纲修正建议
        ('outline_drift', 'pm_agent_outline_drift', _fix_outline_drift, '大纲漂移修正建议'),
        # 视觉一致性自动重试（漫剧角色变脸/画风割裂）
        ('ca_visual_inconsistency', None, _fix_visual_inconsistency, '视觉一致性自动重试'),
        # P0.2: 漫剧 3 维建议型修复（场景/分镜/对话）
        ('ca_scene_discontinuity', None, _fix_scene_discontinuity, '场景连续性修复建议'),
        ('ca_panel_transition', None, _fix_panel_transition, '分镜衔接修复建议'),
        ('ca_dialogue_inconsistency', None, _fix_dialogue_inconsistency, '对话语气统一建议'),
    )
    for bare, prefixed, handler, desc in specs:
        _register_fix_handler(bare, handler, desc)
        if prefixed:
            _register_fix_handler(prefixed, handler, desc)


# 注意：不再在模块加载时自动调用 _register_all_handlers()
# 改为显式调用 register_pm_handlers()，在 register_pm_agent() 中触发
# 这样可以避免模块加载副作用导致的循环导入问题


def register_pm_handlers():
    """显式注册所有修复 handler（应在 register_pm_agent 中调用一次）"""
    _register_all_handlers()
