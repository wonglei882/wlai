"""PM 决策辅助函数模块 — 从 pm_agent_decision.py 拆分而来。

为控制 pm_agent_decision.py 行数（原 1006 行 > 800 红线），将以下低频修改的辅助逻辑拆出：
- _decompose_repair_priority: LLM 问题优先级分解
- _rule_based_sort: 规则引擎排序（LLM 失败降级）
- _failure_status: 冷却/驳回/接受状态判断
- _log_decision: PMDecisionLog 写入

主决策入口 diagnose_and_fix 仍保留在 pm_agent_decision.py。
"""

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, func, desc

from app.logger import get_logger
from app.models.pm_decision_log import PMDecisionLog
from app.services.pm.pm_fix_handlers import (
    FAILED_COOLDOWN_HOURS,
    ENV_FAILED_COOLDOWN_MINUTES,
    _classify_failure,
)

logger = get_logger(__name__)


# =============================================================================
# 问题优先级分解（LLM + 规则引擎降级）
# =============================================================================


async def _decompose_repair_priority(
    db,
    issues: list,
    project_id: str,
    user_id: str,
) -> tuple:
    """用 LLM 分解修复优先级（问题数 > 3 时调用）。

    Args:
        db: 数据库会话
        issues: 问题列表 [{type, severity, chapter_range, ...}]
        project_id: 项目 ID
        user_id: 用户 ID

    Returns:
        (sorted_issues, reasoning) - 排序后的问题列表 + LLM 推理链
    """
    if len(issues) <= 3:
        return issues, '问题数 ≤ 3，无需分解优先级'

    try:
        from app.models.project import Project
        from app.services.ai import AIService
        from app.models.settings import Settings

        # 取项目信息
        project = await db.get(Project, project_id)
        if not project:
            return issues, '项目不存在，使用原始顺序'

        # 从 Settings 表读用户 API 配置
        user_set = await db.execute(select(Settings).where(Settings.user_id == user_id).limit(1))
        user_set = user_set.scalar_one_or_none()

        if not user_set or not user_set.api_key:
            logger.debug('[PM-Agent 目标分解] 用户未配置 API，使用规则引擎排序')
            return _rule_based_sort(issues), '用户未配置 API，规则引擎排序'

        # 构建问题摘要
        issues_summary = [
            {
                'index': i,
                'type': issue.get('type', 'unknown'),
                'severity': issue.get('severity', 'info'),
                'chapter': issue.get('chapter_range', '') or str(issue.get('chapter', '')),
            }
            for i, issue in enumerate(issues)
        ]

        # LLM prompt
        prompt = f"""你是一个小说质量诊断专家。以下是项目"{project.title}"的问题列表：

{json.dumps(issues_summary, ensure_ascii=False, indent=2)}

请根据以下原则排序修复优先级：
1. 严重性优先（critical > warning > info）
2. 依赖关系（角色位置跳 → 伏笔过期 → 世界观漂移 → 大纲漂移）
3. 章节顺序（先修复前面章节）

输出 JSON 格式（仅输出 JSON，无其他内容）：
{{
  "repair_order": [问题索引列表，如 [2, 0, 1, 3]],
  "reasoning": "排序理由（50 字以内）"
}}
"""

        # 初始化 AIService（参数名必须与真实签名一致：曾用 provider/base_url 致 TypeError 被兜底吞掉，LLM 排序永久降级）
        ai_service = AIService(
            user_id=user_id,
            api_provider=user_set.api_provider or 'openai',
            api_key=user_set.api_key,
            api_base_url=user_set.api_base_url or None,
            default_model=user_set.llm_model or 'deepseek-chat',
        )

        # 调用 LLM（P0: 经 call_llm_with_guard 加超时 + 熔断 + 重试，防卡死）
        from app.services.pm.pm_llm_guard import call_llm_with_guard

        from app.services.pm.pm_token_budget import BudgetContext

        # 输出预算随问题数伸缩：repair_order 数组 + 可能的 markdown 包裹与冗长理由。
        # 固定值曾两度生产截断（300 首爆、800 仍击穿 25-40 问题项目）→ 动态公式封顶防失控
        max_tokens = min(600 + len(issues) * 30, 3000)

        # 预算上下文提升为局部变量，便于调用后读取 exhausted 标志（预算耗尽留痕）
        budget_ctx = BudgetContext(user_id=user_id, project_id=project_id, feature='decision', action='decompose_priority', db=db)
        response = await call_llm_with_guard(
            ai_service.generate_text,
            breaker_name='decompose_priority',
            prompt=prompt,
            provider=user_set.api_provider or 'openai',
            model=user_set.llm_model or 'deepseek-chat',
            max_tokens=max_tokens,
            temperature=0.3,
            budget_ctx=budget_ctx,
        )
        if not response:
            logger.warning('[PM-Agent 目标分解] LLM 调用失败/超时，回退规则引擎排序')
            if getattr(budget_ctx, 'exhausted', False):
                # 预算耗尽导致的降级：reasoning 带显式标记，供 _finalize_decision 写入 decision_reason
                return _rule_based_sort(issues), 'budget_degraded: 今日 token 预算已耗尽，规则引擎排序'
            return _rule_based_sort(issues), 'LLM 调用失败，规则引擎排序'

        # 解析响应：generate_text 真实返回 Dict（content/finish_reason/usage），
        # 曾误按字符串 .strip() → AttributeError 被兜底吞掉、LLM 白调用（回归 #3）
        if not isinstance(response, dict):
            logger.warning(f'[PM-Agent 目标分解] LLM 响应类型异常 {type(response).__name__}，回退规则引擎排序')
            return _rule_based_sort(issues), 'LLM 响应格式异常，规则引擎排序'
        if response.get('finish_reason') == 'length':
            # 输出被 max_tokens 截断，JSON 必不完整——显式降级留痕，避免 json.loads 抛错掩盖真因
            logger.warning('[PM-Agent 目标分解] LLM 输出被截断(finish_reason=length)，回退规则引擎排序')
            return _rule_based_sort(issues), 'LLM 输出被截断(max_tokens 不足)，规则引擎排序'
        response_text = (response.get('content') or '').strip()
        # 提取 JSON（可能被 markdown 包裹）
        if '```json' in response_text:
            response_text = response_text.split('```json')[1].split('```')[0].strip()
        elif '```' in response_text:
            response_text = response_text.split('```')[1].split('```')[0].strip()

        result = json.loads(response_text)
        repair_order = result.get('repair_order', list(range(len(issues))))
        reasoning = result.get('reasoning', 'LLM 未提供理由')

        # 按顺序重排 issues
        sorted_issues = [issues[i] for i in repair_order if i < len(issues)]
        # 补充可能遗漏的索引
        for _i, issue in enumerate(issues):
            if issue not in sorted_issues:
                sorted_issues.append(issue)

        logger.info(f'[PM-Agent 目标分解] LLM 排序完成: {len(sorted_issues)} 问题，理由: {reasoning[:50]}')

        return sorted_issues, reasoning

    except Exception as e:
        logger.warning(f'[PM-Agent 目标分解] LLM 调用失败（回退规则引擎）: {e}')
        return _rule_based_sort(issues), f'LLM 调用失败，规则引擎排序: {e}'


def _rule_based_sort(issues: list) -> list:
    """规则引擎排序（LLM 失败时的降级方案）。

    排序规则：
    1. severity: critical > warning > info
    2. type: character > foreshadow > world > outline
    3. chapter: 小号优先
    """
    severity_order = {'critical': 0, 'warning': 1, 'info': 2}
    type_order = {
        'character': 0,
        'location': 0,
        'foreshadow': 1,
        'world': 2,
        'worldview': 2,
        'outline': 3,
        'quality': 4,
    }

    def sort_key(issue):
        # 严重性
        sev = severity_order.get(issue.get('severity', 'info'), 2)
        # 类型（精确匹配：子串匹配会把 'character_location_jump' 误判为 'character'）
        typ = type_order.get(issue.get('type') or '', 5)
        # 章节
        chapter = issue.get('chapter') or issue.get('chapter_number') or 999
        try:
            chapter = int(chapter)
        except (TypeError, ValueError):
            chapter = 999

        return (sev, typ, chapter)

    return sorted(issues, key=sort_key)


# =============================================================================
# 失败状态检查（冷却/驳回/接受）
# =============================================================================


async def _failure_status(db, project_id: str, diag_type: str) -> str:
    """返回该 project+type 的失败/驳回/接受状态：'cooldown' / 'manual' / 'skip_approved' / ''（无限制）。

    - 最近有 user_feedback='rejected' → 'manual'（用户驳回过，转人工）
    - 最近有 user_feedback='approved' 且 7 天内 → 'skip_approved'（用户已接受，跳过重复修复）
    - 最近 failed：环境类 10 分钟内、逻辑类 24h 内 → 'cooldown'
    """
    try:
        # 1. 用户驳回检查（永久转人工，直到有新反馈）
        rej = await db.execute(
            select(func.count())
            .select_from(PMDecisionLog)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type == diag_type,
                PMDecisionLog.user_feedback == 'rejected',
            )
        )
        if (rej.scalar_one() or 0) > 0:
            return 'manual'

        # 2. 用户接受检查（7 天内不再重复修复）
        approved_r = await db.execute(
            select(func.count())
            .select_from(PMDecisionLog)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type == diag_type,
                PMDecisionLog.user_feedback == 'approved',
                PMDecisionLog.created_at >= datetime.now() - timedelta(days=7),
            )
        )
        if (approved_r.scalar_one() or 0) > 0:
            return 'skip_approved'

        # 3. 失败冷却检查（环境类 10 分钟，逻辑类 24h）
        # 扫描整个冷却窗口内的全部失败记录（而非仅最新一条）：
        # 若最新失败是已过期的 env 类，但窗口内仍有未过期的 logic 失败，仍应冷却。
        failed_rows = await db.execute(
            select(PMDecisionLog.fix_action, PMDecisionLog.fix_details, PMDecisionLog.created_at)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type == diag_type,
                PMDecisionLog.fix_result == 'failed',
                PMDecisionLog.created_at >= datetime.now() - timedelta(hours=FAILED_COOLDOWN_HOURS),
            )
            .order_by(desc(PMDecisionLog.created_at))
        )
        now = datetime.now()
        for fix_action, fix_details_json, created_at in failed_rows.all():
            # 显式分类优先：fix_details.failure_kind（由异常类型判定写入），缺失/非法时回退关键词法
            failure_kind = None
            if fix_details_json:
                try:
                    details = json.loads(fix_details_json)
                    if isinstance(details, dict):
                        failure_kind = details.get('failure_kind')
                except (TypeError, ValueError):
                    failure_kind = None
            if failure_kind not in ('env', 'logic'):
                failure_kind = _classify_failure(fix_action or '')
            if failure_kind == 'env':
                # 环境类失败：10 分钟内冷却
                if now - created_at < timedelta(minutes=ENV_FAILED_COOLDOWN_MINUTES):
                    return 'cooldown'
            else:
                # 逻辑类失败：24h 内冷却
                if now - created_at < timedelta(hours=FAILED_COOLDOWN_HOURS):
                    return 'cooldown'
    except Exception as e:
        logger.debug(f'[PM-Agent 决策] 冷却检查异常（放行）: {e}')
        return ''
    return ''


# =============================================================================
# 决策记录写入
# =============================================================================


async def _log_decision(
    db,
    project_id: str,
    user_id: str,
    issue: dict[str, Any],
    severity: str,
    decision: str,
    decision_reason: str,
    fix_action: str,
    fix_result: str,
    fix_attempted: bool,
    verified: bool,
    verified_at: datetime,
    verify_message: str,
    scan_round: str,
    original_message: str,
    fix_details: str = None,
) -> PMDecisionLog:
    """将决策结果写入 PMDecisionLog。"""
    # 防重：同一 scan_round + 同类型 + 同章节不重复写入
    if scan_round:
        ch_num_for_check = 0
        cr = issue.get('chapter_range', '')
        if cr:
            try:
                ch_num_for_check = int(cr.split('→')[0].strip().lstrip('第').rstrip('章'))
            except Exception:
                ch_num_for_check = issue.get('from_chapter', 0) or 0
        else:
            ch_num_for_check = issue.get('from_chapter', 0) or 0
        existing = await db.execute(
            select(PMDecisionLog)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type == issue.get('type', ''),
                PMDecisionLog.chapter_number == ch_num_for_check,
                PMDecisionLog.scan_round == scan_round,
            )
            .limit(1)
        )
        _existing_log = existing.scalar_one_or_none()
        if _existing_log:
            log = _existing_log
            # 更新记录
            log.decision = decision
            log.fix_action = fix_action
            log.fix_result = fix_result
            log.verified = verified
            log.verified_at = verified_at
            log.verify_message = verify_message
            log.updated_at = datetime.now()
            if fix_details:
                log.fix_details = fix_details
            return log

    chapter_num = 0
    cr = issue.get('chapter_range', '')
    if cr:
        try:
            chapter_num = int(cr.split('→')[0].strip().lstrip('第').rstrip('章'))
        except Exception:
            chapter_num = issue.get('from_chapter', 0) or 0
    else:
        chapter_num = issue.get('planted_chapter', 0) or 0

    log = PMDecisionLog(
        project_id=project_id,
        user_id=user_id,
        diag_type=issue.get('type', ''),
        chapter_number=chapter_num,
        severity=severity,
        original_message=original_message,
        decision=decision,
        decision_reason=decision_reason,
        fix_action=fix_action,
        fix_result=fix_result,
        fix_attempted=fix_attempted,
        verified=verified,
        verified_at=verified_at,
        verify_message=verify_message,
        scan_round=scan_round,
        fix_details=fix_details,
    )
    db.add(log)
    return log


async def _log_deduped_decision(
    db,
    project_id: str,
    user_id: str,
    issue: dict[str, Any],
    severity: str,
    scan_round: str,
    original_message: str,
    decision: str,
    decision_reason: str,
    verify_message: str,
    fix_result: str,
    window_hours: float = 1.0,
) -> int | None:
    """窗口内按 (project_id, diag_type, decision) 去重地落一条决策日志。

    供 manual / cooldown / 重试上限等"短路决策"分支复用（原三分支各写一遍
    去重查询 + _log_decision + commit/rollback，共约 60 行重复）。

    Returns:
        PMDecisionLog.id；窗口内已有同型决策或写入失败时返回 None（非阻塞）。
    """
    try:
        dup = await db.execute(
            select(func.count())
            .select_from(PMDecisionLog)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type == issue.get('type', ''),
                PMDecisionLog.decision == decision,
                PMDecisionLog.created_at >= datetime.now() - timedelta(hours=window_hours),
            )
        )
        if (dup.scalar_one() or 0) > 0:
            await db.rollback()
            return None
        log = await _log_decision(
            db=db,
            project_id=project_id,
            user_id=user_id,
            issue=issue,
            severity=severity,
            decision=decision,
            decision_reason=decision_reason,
            fix_action='',
            fix_result=fix_result,
            fix_attempted=False,
            verified=False,
            verified_at=None,
            verify_message=verify_message,
            scan_round=scan_round,
            original_message=original_message,
            fix_details=None,
        )
        await db.commit()
        return log.id if log else None
    except Exception as log_e:
        logger.warning(f'[PM-Agent 决策] 记录 {decision} 决策失败（非阻塞）: {log_e}')
        await db.rollback()
        return None


# =============================================================================
# P0: 多因子评分模型（供 _decide_action 调用）
# =============================================================================


def _compute_decision_score(
    severity_val: float,
    success_rate: float,
    cooldown_penalty: float,
    issue_confidence: float = 0.8,
    drift_risk: float = 0.0,
    uncertainty_penalty: float = 0.0,
) -> float:
    """
    决策分 = 修复收益 - 修复风险 - 不确定性惩罚。

    L4 方向2：引入不确定性惩罚（Thompson Sampling 思路）。
    Beta 分布的 std 越大（样本越少），惩罚越重，倾向于保守决策。

    Args:
        severity_val: 严重性 (critical=1.0, warning=0.6, info=0.2)
        success_rate: 项目历史成功率 [0.0, 1.0]
        cooldown_penalty: 近期失败冷却惩罚 [0.0, 1.0]
        issue_confidence: 扫描器置信度 [0.0, 1.0]
        drift_risk: 目标偏离风险 [0.0, 1.0]
        uncertainty_penalty: Beta 不确定性惩罚 = k * std [0.0, ~0.29]
            样本少时 std 大 → 惩罚重 → 决策分降低 → 倾向 manual/suggestion

    Returns:
        决策分 [-0.5, 1.0]
        ≥ 0.50 → auto_fix  |  0.30~0.49 → auto_fix (低风险 suggestion_only)  |  < 0.30 → manual
    """
    # 有效成功率 = 均值 - 不确定性惩罚（样本少时拉低有效成功率）
    effective_rate = max(0.0, success_rate - uncertainty_penalty)
    benefit = severity_val * issue_confidence * (0.5 + 0.5 * effective_rate)
    risk = 0.6 * cooldown_penalty + 0.4 * drift_risk
    score = benefit - risk
    return max(-0.5, min(1.0, score))


# =============================================================================
# P0: 近期同类失败次数（供 _decide_action 计算 cooldown_penalty）
# =============================================================================


async def _get_recent_failure_count(
    db,
    project_id: str,
    diag_type: str,
    window_hours: int = 1,
) -> int:
    """
    查询该项目该类型最近 1h 内失败次数（用于 cooldown_penalty 连续化）。

    Returns:
        失败次数 int
    """
    try:
        rows = await db.execute(
            select(func.count())
            .select_from(PMDecisionLog)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type == diag_type,
                PMDecisionLog.fix_result == 'failed',
                PMDecisionLog.created_at >= datetime.now() - timedelta(hours=window_hours),
            )
        )
        return rows.scalar_one() or 0
    except Exception:
        return 0


async def _get_consecutive_failures(
    db,
    project_id: str,
    diag_type: str,
    window_hours: int = 1,
) -> int:
    """
    查询该项目该类型最近 1h 内的连续失败次数（按时间倒序）。

    Returns:
        连续失败次数 int
    """
    try:
        rows = await db.execute(
            select(PMDecisionLog.fix_result)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type == diag_type,
                PMDecisionLog.created_at >= datetime.now() - timedelta(hours=window_hours),
            )
            .order_by(desc(PMDecisionLog.created_at))
        )
        count = 0
        for (result,) in rows.all():
            if result == 'failed':
                count += 1
            else:
                break
        return count
    except Exception:
        return 0


async def _get_recent_attempt_count(
    db,
    project_id: str,
    diag_type: str,
    days: int = 7,
) -> int:
    """查询该项目该类型最近 N 天内的修复尝试次数（fix_attempted=True，含成功与失败）。

    用于跨轮重试上限（止血 #3）：同一问题每轮巡检都重试仍无效时转人工，
    防止"扫描→修复→下轮再扫描→再修复"的无限循环。
    """
    try:
        rows = await db.execute(
            select(func.count())
            .select_from(PMDecisionLog)
            .where(
                PMDecisionLog.project_id == project_id,
                PMDecisionLog.diag_type == diag_type,
                PMDecisionLog.fix_attempted.is_(True),
                PMDecisionLog.created_at >= datetime.now() - timedelta(days=days),
            )
        )
        return rows.scalar_one() or 0
    except Exception:
        return 0


async def _get_recent_decision_failures(db, project_id: str, diag_type: str) -> dict:
    """L5 反思闭环：查询同类决策修复的累计失败模式（由 pm_decision_verify 回写）。

    Returns:
        {'count': int, 'last_cause': str}；查询异常时返回空 dict（放行，不阻塞决策）。
    """
    try:
        from app.models.pm_v2 import FailurePattern

        r = await db.execute(
            select(FailurePattern)
            .where(
                FailurePattern.project_id == project_id,
                FailurePattern.pattern_type == f'decision_{diag_type}',
            )
            .limit(1)
        )
        pat = r.scalar_one_or_none()
        if not pat:
            return {}
        return {
            'count': pat.occurrence_count or 0,
            'last_cause': (pat.root_cause or pat.error_description or '')[:150],
        }
    except Exception:
        return {}
