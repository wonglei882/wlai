"""PM 巡检扫描器 — 诊断维度注册表 + 各维度扫描函数。

从 pm_agent.py 拆分而来，职责：
- SCAN_REGISTRY / scan_dimension 装饰器（数据驱动的维度注册）
- 各维度扫描函数：角色跳变、伏笔老化、世界观漂移、大纲漂移
- 诊断日志写入 _write_diagnostic_from_scan
- 章节号解析辅助 _extract_chapter_from_range

依赖说明：
- pm_scanners.py 不依赖 pm_agent.py（避免循环导入）
- pm_agent.py 通过 register_pm_handlers 时触发本模块的装饰器加载
"""

import json
import math
from typing import Any

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

import logging
from app.services.pm.pm_consistency_guardian import PMConsistencyGuardian
from app.services.pm.scan_support import has_unresolved_diagnostic, load_character_names

logger = logging.getLogger(__name__)


def _safe_json_loads(raw) -> dict[str, Any]:
    """兼容 str/JSON 与已解析 dict 两种存储形态的解析，失败回退空 dict。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except Exception:  # noqa: S110 -- 解析失败属数据脏数据，静默跳过该行
            return {}
    return {}


# 伏笔类型 → 指数衰减 lambda（模块级常量，避免每行循环重复构建）
# identity 0.12（回收窗口约8章）/ mystery 0.10 / event 0.08 / relationship、item 0.06
_FORESHADOW_LAMBDA_BY_CATEGORY = {
    'identity': 0.12,
    'mystery': 0.10,
    'event': 0.08,
    'relationship': 0.06,
    'item': 0.06,
}
_FORESHADOW_LAMBDA_DEFAULT = 0.10

# 巡检只扫最近 N 个章节（避免全量扫描耗时过长）
RECENT_CHAPTER_LIMIT = 20

# 伏笔老化阈值（planted 后超过此章节数仍未 resolved → 预警）
FORESHADOW_LOW_AGE_THRESHOLD = 10
# P1-1 Z-score 扫描参数
Z_SCORE_THRESHOLD = 2.0  # Z > 2.0 视为异常（约 95% 置信）
MIN_SAMPLES_FOR_ZSCORE = 5  # 样本量 < 5 退回硬阈值


# =============================================================================
# 诊断维度注册表（数据驱动：新增维度只需加 @scan_dimension 装饰器）
# =============================================================================
SCAN_REGISTRY: dict[str, dict[str, Any]] = {}


def scan_dimension(name: str, issue_type: str, diag_msg_fn):
    """
    注册一个诊断维度。

    Args:
        name: 维度标识（如 "character_consistency"）
        issue_type: PM 诊断类型（如 "pm_agent_character_jump"）
        diag_msg_fn: 从 issue dict 生成诊断消息的函数

    Raises:
        ValueError: 重复注册同名维度（防止无声覆盖）
    """

    def decorator(fn):
        if name in SCAN_REGISTRY:
            existing = SCAN_REGISTRY[name]
            if existing['fn'] is not fn:
                raise ValueError(
                    f'scan_dimension 重复注册: name={name} '
                    f'已注册于 {existing["fn"].__module__}.{existing["fn"].__name__}, '
                    f'当前 {fn.__module__}.{fn.__name__}'
                )
        SCAN_REGISTRY[name] = {
            'fn': fn,
            'issue_type': issue_type,
            'diag_msg_fn': diag_msg_fn,
        }
        return fn

    return decorator


# =============================================================================
# 巡检函数（按项目维度）
# =============================================================================


@scan_dimension(
    'character_consistency',
    'pm_agent_character_jump',
    lambda i: f'[PM-Agent] 角色 {i.get("character", "")} 位置跳变 {i.get("from", "")} → {i.get("to", "")}',
)
async def _scan_character_consistency(db: AsyncSession, project_id: str, user_id: str) -> list[dict[str, Any]]:
    """检测角色的位置/关系在相邻章节间的跳变（Z-score 异常检测）。

    P1-1 升级：
    - 样本量 >= MIN_SAMPLES_FOR_ZSCORE：用 Z-score 检测异常跳变
    - 样本量 < 5：退回硬阈值（相邻章 location 不同即报）
    - Z > Z_SCORE_THRESHOLD 视为异常跳变（约 95% 置信）
    """
    issues = []
    try:
        result = await db.execute(
            text("""
                SELECT chapter_number, character_states
                FROM pm_consistency_state
                WHERE project_id = :pid
                ORDER BY chapter_number DESC
                LIMIT :limit
            """),
            {'pid': project_id, 'limit': RECENT_CHAPTER_LIMIT + 1},
        )
        rows = result.fetchall()
        n_samples = len(rows)

        # 收集角色历史 location 频次（用于 Z-score）
        char_location_hist: dict[str, dict[str, int]] = {}  # char -> {loc: count}
        for row in rows:
            cs = _safe_json_loads(row[1])
            for name, state in cs.items():
                loc = state.get('location', '') if isinstance(state, dict) else ''
                if loc:
                    char_location_hist.setdefault(name, {})
                    char_location_hist[name][loc] = char_location_hist[name].get(loc, 0) + 1

        # 相邻章对比
        for i in range(len(rows) - 1):
            ch1, ch2 = rows[i][0], rows[i + 1][0]
            cs1, cs2 = _safe_json_loads(rows[i][1]), _safe_json_loads(rows[i + 1][1])

            all_names = set(cs1.keys()) | set(cs2.keys())
            for name in all_names:
                s1 = cs1.get(name, {})
                s2 = cs2.get(name, {})
                loc1 = s1.get('location', '') if isinstance(s1, dict) else ''
                loc2 = s2.get('location', '') if isinstance(s2, dict) else ''

                if not (loc1 and loc2 and loc1 != loc2):
                    continue

                # 样本量 < 5：硬阈值
                if n_samples < MIN_SAMPLES_FOR_ZSCORE:
                    issues.append(
                        {
                            'type': 'character_location_jump',
                            'chapter_range': f'第{ch2}章 → 第{ch1}章',
                            'character': name,
                            'from': loc1,
                            'to': loc2,
                            'detection': 'hard_threshold',
                        }
                    )
                    continue

                # Z-score 检测
                hist = char_location_hist.get(name, {})
                total = sum(hist.values())
                if total == 0:
                    continue

                # 计算该角色 location 的概率分布
                p1 = hist.get(loc1, 0) / total
                p2 = hist.get(loc2, 0) / total
                mean_p = (p1 + p2) / 2.0
                # 用 Bernoulli 方差近似
                var_p = mean_p * (1 - mean_p) if 0 < mean_p < 1 else 0.25
                std_p = math.sqrt(var_p) if var_p > 0 else 0.5

                # Z = |观察值 - 均值| / 标准差（跳变 = 两个位置概率差异）
                observed_diff = abs(p1 - p2)
                z_score = observed_diff / std_p if std_p > 0 else 0.0

                if z_score > Z_SCORE_THRESHOLD:
                    issues.append(
                        {
                            'type': 'character_location_jump',
                            'chapter_range': f'第{ch2}章 → 第{ch1}章',
                            'character': name,
                            'from': loc1,
                            'to': loc2,
                            'detection': 'z_score',
                            'z_score': round(z_score, 2),
                        }
                    )

    except Exception as e:
        logger.warning(f'[PM-Agent] 角色状态扫描异常 project={project_id}: {e}')
    return issues


@scan_dimension(
    'foreshadow_age',
    'pm_agent_foreshadow_stale',
    lambda i: f'[PM-Agent] 伏笔「{i.get("title", "")}」已埋 {i.get("age", 0)} 章仍未解决',
)
async def _scan_foreshadow_age(db: AsyncSession, project_id: str, user_id: str) -> list[dict[str, Any]]:
    """检测 planted 超过阈值的伏笔（可能已失效）。"""
    issues = []
    try:
        from app.models.chapter import Chapter
        from app.models.foreshadow import Foreshadow
        from sqlalchemy import and_

        # 龄期基准：真实章节进度优先；旧口径 MAX(plant_chapter_number) 系统性低估龄期导致漏检
        latest_ch_result = await db.execute(select(func.max(Chapter.chapter_number)).where(Chapter.project_id == project_id))
        latest_ch = latest_ch_result.scalar() or 0

        if latest_ch == 0:
            fallback_result = await db.execute(select(func.max(Foreshadow.plant_chapter_number)).where(Foreshadow.project_id == project_id))
            latest_ch = fallback_result.scalar() or 0
        if latest_ch == 0:
            return issues

        # 找 planted 但超过阈值仍未 resolved 的伏笔
        threshold = latest_ch - FORESHADOW_LOW_AGE_THRESHOLD
        if threshold <= 0:
            return issues

        result = await db.execute(
            select(Foreshadow)
            .where(
                and_(
                    Foreshadow.project_id == project_id,
                    Foreshadow.status == 'planted',
                    Foreshadow.plant_chapter_number.is_not(None),
                    Foreshadow.plant_chapter_number <= threshold,
                )
            )
            .limit(20)
        )
        for fs in result.scalars().all():
            age = latest_ch - (fs.plant_chapter_number or 0)
            # P0: 指数衰减紧急度 urgency = 1 - e^(-lambda * age)，lambda 按伏笔类型拟合
            _lambda = _FORESHADOW_LAMBDA_BY_CATEGORY.get(fs.category or '', _FORESHADOW_LAMBDA_DEFAULT)
            urgency_score = 1.0 - math.exp(-_lambda * age)
            # 紧急度分级：0.5 以上中度关注，0.8 以上高优先级
            if urgency_score < 0.3:
                continue  # 未达到预警阈值，跳过
            issues.append(
                {
                    'type': 'foreshadow_stale',
                    'foreshadow_id': str(fs.id),
                    'title': fs.title or '',
                    'planted_chapter': fs.plant_chapter_number,
                    'current_chapter': latest_ch,
                    'age': age,
                    'urgency_score': round(urgency_score, 3),
                    'hint_text': (fs.hint_text or '')[:100],
                }
            )

    except Exception as e:
        logger.warning(f'[PM-Agent] 伏笔老化扫描异常 project={project_id}: {e}')
    return issues


# 已从 SCAN_REGISTRY 摘除：unresolved 诊断没有 fix handler，扫描出来永远是 skip，
# 每轮巡检只会产生空转查询。真正的解决路径是各 fix 函数在修复成功后
# 调用 _resolve_diagnostic_log 将诊断标记 resolved。
# 保留函数定义供手动调用/调试。
# deprecated: 已从巡检注册表摘除，不再自动扫描
async def _scan_unresolved_diagnostics(db: AsyncSession, project_id: str, user_id: str) -> list[dict[str, Any]]:
    """检测未解决的诊断日志。（已从巡检注册表摘除）"""
    issues = []
    try:
        from app.models.pm_diagnostic_log import PMDiagnosticLog

        result = await db.execute(
            select(PMDiagnosticLog)
            .where(
                PMDiagnosticLog.project_id == project_id,
                PMDiagnosticLog.resolved.is_(False),
            )
            .order_by(PMDiagnosticLog.created_at.desc())
            .limit(20)
        )
        for dl in result.scalars().all():
            issues.append(
                {
                    'type': 'unresolved_diagnostic',
                    'log_id': str(dl.id),
                    'diag_type': dl.diag_type or '',
                    'chapter': dl.chapter_number or 0,
                    'created_at': str(dl.created_at or ''),
                    'message': (dl.message or '')[:200],
                }
            )

    except Exception as e:
        logger.debug(f'[PM-Agent] 诊断日志扫描异常 project={project_id}: {e}')
    return issues


@scan_dimension(
    'world_rule_drift',
    'pm_agent_world_drift',
    lambda i: f'[PM-Agent] 世界观规则漂移（第{i.get("from_chapter")}章→{i.get("to_chapter")}章）',
)
async def _scan_world_rule_drift(db: AsyncSession, project_id: str, user_id: str) -> list[dict[str, Any]]:
    """检测世界观规则在相邻章节间的漂移（通过 PMConsistencyState 的 world_states hash）。"""
    issues = []
    try:
        result = await db.execute(
            text("""
                SELECT chapter_number, world_states
                FROM pm_consistency_state
                WHERE project_id = :project_id
                ORDER BY chapter_number DESC
                LIMIT :limit
            """),
            {'project_id': project_id, 'limit': RECENT_CHAPTER_LIMIT},
        )
        rows = result.fetchall()

        prev_hash = None
        prev_ch = None
        prev_appeared = None
        for row in rows:
            ch, ws_raw = row[0], row[1]
            ws = _safe_json_loads(ws_raw)
            curr_hash = ws.get('_world_rules_hash', '')
            curr_appeared = ws.get('_appeared_rules', [])

            # 修复：原逻辑仅对比 hash，但 hash 变化不一定等于漂移严重
            # （可能只是少提了一两个词）。改为：hash 不同时进一步计算规则命中差异率，
            # 差异 > 50% 才算实质性漂移，避免误报。
            if prev_hash and prev_hash != curr_hash and curr_hash:
                # 计算相邻章节规则命中差异率
                set_prev = set(prev_appeared) if prev_appeared else set()
                set_curr = set(curr_appeared) if curr_appeared else set()
                union = set_prev | set_curr
                diff_rate = len(set_prev ^ set_curr) / len(union) if union else 0.0

                if diff_rate > 0.5:
                    issues.append(
                        {
                            'type': 'world_rule_drift',
                            'from_chapter': ch,
                            'to_chapter': prev_ch,
                            'hash_from': curr_hash[:16],
                            'hash_to': prev_hash[:16],
                            'diff_rate': round(diff_rate, 2),
                        }
                    )
            prev_hash = curr_hash
            prev_ch = ch
            prev_appeared = curr_appeared

        # 收敛去重：同 project 同 diag_type 存在未决记录（resolved=False）时跳过产出，
        # 避免同一漂移每轮巡检重复入账（生产实证 72 次重报；_upsert_diagnostic_log
        # 的 1h 去重窗口挡不住跨轮重复）。修复后 resolved=True 会重新放行新告警。
        if issues and await has_unresolved_diagnostic(db, project_id, 'pm_agent_world_drift'):
            logger.info(f'[PM-Agent] 世界观漂移存在未决记录，本轮跳过重复告警 project={project_id[:8]} count={len(issues)}')
            return []

    except Exception as e:
        logger.warning(f'[PM-Agent] 世界观漂移扫描异常 project={project_id}: {e}')
    return issues


# P2: 大纲漂移 — 重新启用，已补齐修复路径（LLM 生成大纲修正建议 + 更新大纲结构）
# 注意：outlines 表没有 chapter_number 列（历史 bug 源头），章号代理用 order_index
_OUTLINE_DRIFT_SQL = text("""
    WITH ranked AS (
        SELECT
            o.id, o.order_index AS chapter_number, o.structure,
            ROW_NUMBER() OVER (
                PARTITION BY o.project_id ORDER BY o.order_index DESC
            ) AS rn
        FROM outlines o
        WHERE o.project_id = :project_id
          AND o.structure IS NOT NULL
          AND o.structure != ''
    )
    SELECT r1.chapter_number AS ch1, r1.structure AS s1,
           r2.chapter_number AS ch2, r2.structure AS s2
    FROM ranked r1
    JOIN ranked r2 ON r2.rn = r1.rn + 1
    LIMIT :limit
""")


@scan_dimension(
    'outline_drift',
    'pm_agent_outline_drift',
    lambda i: f'[PM-Agent] 大纲漂移: {"; ".join(i.get("drifts", [])[:2])}',
)
async def _scan_outline_drift(db: AsyncSession, project_id: str, user_id: str) -> list[dict[str, Any]]:
    """检测大纲漂移：对比相邻章节的大纲内容，检测结构变化。"""
    issues = []
    try:
        # 查最近 N 个有 outline 记录的大纲
        result = await db.execute(
            _OUTLINE_DRIFT_SQL,
            {'project_id': project_id, 'limit': RECENT_CHAPTER_LIMIT},
        )
        rows = result.fetchall()

        # 角色白名单：候选名必须对应本项目注册角色才参与对比，
        # 防止正则裸抽取的汉字碎片（「化肥到货」等）被当角色名误报
        known_names = await load_character_names(db, project_id)

        guardian = PMConsistencyGuardian(project_id=project_id, db=db)
        for row in rows:
            ch1, s1_raw, ch2, s2_raw = row[0], row[1] or '', row[2], row[3] or ''
            drifts = await guardian.detect_outline_drift(s1_raw, s2_raw, known_names=known_names)
            if drifts:
                issues.append(
                    {
                        'type': 'outline_drift',
                        'chapter_number': ch1,
                        'chapter_range': f'第{ch2}章 → 第{ch1}章',
                        'drifts': drifts,
                    }
                )

    except Exception as e:
        logger.warning(f'[PM-Agent] 大纲漂移扫描异常 project={project_id}: {e}')
    return issues


# =============================================================================
# P0.1: 质量评分维度 — 接入 quality_scorer 7 维评分到巡检循环
# =============================================================================

# 质量评分低于此值才生成 issue（与 PMQualityScorerV2.PASS_THRESHOLD 对齐）
QUALITY_SCORE_THRESHOLD = 70


@scan_dimension(
    'quality_score',
    'pm_agent_quality_score_low',
    lambda i: (
        f'[PM-Agent] 第{i.get("chapter_number", "?")}章质量评分 {i.get("total_score", 0):.1f} < {QUALITY_SCORE_THRESHOLD}'
        f'，低分维度: {"; ".join(i.get("low_dims", []))}'
    ),
)
async def _scan_quality_score(db: AsyncSession, project_id: str, user_id: str) -> list[dict[str, Any]]:
    """对最新章节执行 7 维质量评分（pacing/dialogue/hook/...），低于阈值生成 issue。

    使用 PMQualityScorerV2.score()，支持 AI 评分 + fallback 规则评分。
    AIService 通过 pm_ai_client 获取（用户级缓存），获取失败时自动降级为规则评分。
    """
    issues: list[dict[str, Any]] = []
    try:
        result = await db.execute(
            text("""
                SELECT id, chapter_number, content
                FROM chapters
                WHERE project_id = :project_id
                  AND content IS NOT NULL
                  AND length(content) > 200
                ORDER BY chapter_number DESC
                LIMIT 1
            """),
            {'project_id': project_id},
        )
        row = result.fetchone()
        if not row:
            return issues

        chapter_id, chapter_number, content = row[0], row[1], row[2] or ''

        # 获取 AIService（用户级缓存，失败则用规则评分）
        ai = None
        try:
            from app.services.pm.pm_ai_client import get_pm_ai_client

            ai = await get_pm_ai_client(user_id, db)
        except Exception:  # noqa: S110 -- AIService 获取失败属预期降级路径，静默回退规则评分
            pass

        from app.services.pm.quality_scorer import PMQualityScorerV2

        scorer = PMQualityScorerV2(ai_service=ai)
        score_result = await scorer.score(content, context={})

        if not score_result.passed:
            low_dims = [dim for dim, sc in score_result.scores.items() if sc < 60]
            issues.append(
                {
                    'type': 'quality_score_low',
                    'chapter_number': chapter_number,
                    'chapter_id': str(chapter_id),
                    'total_score': score_result.total_score,
                    'low_dims': low_dims,
                    'suggestions': score_result.suggestions,
                }
            )

    except Exception as e:
        logger.warning(f'[PM-Agent] 质量评分扫描异常 project={project_id}: {e}')
    return issues


# =============================================================================
# P0.2: 段落格式维度 — 用 _format.py 的 110 字规则检测超长段落
# =============================================================================

# 段落最大字数（与 _format.py _MAX_PARA 一致）
PARAGRAPH_MAX_CHARS = 110
# 超长段落数超过此阈值才报 issue（避免噪音）
PARAGRAPH_LONG_THRESHOLD = 3


@scan_dimension(
    'paragraph_format',
    'pm_agent_paragraph_too_long',
    lambda i: (
        f'[PM-Agent] 第{i.get("chapter_number", "?")}章有 {i.get("long_para_count", 0)} 个超长段落（>{PARAGRAPH_MAX_CHARS}字）'
        f'，总计 {i.get("total_paras", 0)} 段'
    ),
)
async def _scan_paragraph_format(db: AsyncSession, project_id: str, user_id: str) -> list[dict[str, Any]]:
    """检测最新章节中超过 110 字的段落数量（与 _format.py 的 _MAX_PARA 对齐）。

    网文手机阅读舒适区间为 30~110 字/段，超过 110 字的段落会被
    format_webnovel_paragraphs() 拆分。如果生成时格式化失败或跳过，
    巡检时应该能发现这些遗留的超长段落。
    """
    issues: list[dict[str, Any]] = []
    try:
        result = await db.execute(
            text("""
                SELECT id, chapter_number, content
                FROM chapters
                WHERE project_id = :project_id
                  AND content IS NOT NULL
                  AND length(content) > 200
                ORDER BY chapter_number DESC
                LIMIT 1
            """),
            {'project_id': project_id},
        )
        row = result.fetchone()
        if not row:
            return issues

        chapter_id, chapter_number, content = row[0], row[1], row[2] or ''

        # 按 \n\n 分段（与 format_webnovel_paragraphs 的拆分逻辑一致）
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        long_paras = [p for p in paragraphs if len(p) > PARAGRAPH_MAX_CHARS]

        if len(long_paras) > PARAGRAPH_LONG_THRESHOLD:
            issues.append(
                {
                    'type': 'paragraph_too_long',
                    'chapter_number': chapter_number,
                    'chapter_id': str(chapter_id),
                    'long_para_count': len(long_paras),
                    'total_paras': len(paragraphs),
                    'sample': (long_paras[0][:80] + '...') if long_paras else '',
                }
            )

    except Exception as e:
        logger.warning(f'[PM-Agent] 段落格式扫描异常 project={project_id}: {e}')
    return issues


async def _write_diagnostic_from_scan(
    db: AsyncSession, project_id: str, user_id: str, issue_type: str, chapter_number: int, message: str, details: dict[str, Any]
):
    """将巡检发现的问题写入 PMDiagnosticLog 表（upsert 模式，同类型同章节只保留最新一条）。"""
    try:
        from app.services.inspiration_sub.diagnostic import _upsert_diagnostic_log

        details_str = json.dumps(details, ensure_ascii=False)[:490]
        await _upsert_diagnostic_log(
            db=db,
            project_id=project_id,
            user_id=user_id,
            diag_type=issue_type,
            severity='warning',
            message=message[:490],
            suggestion=details_str,
            chapter_number=chapter_number,
        )
    except Exception as e:
        logger.warning(f'[PM-Agent] 写入诊断日志失败: {e}')


def _extract_chapter_from_range(chapter_range: str):
    """从 '第12章→第15章' 提取起始章节号。"""
    try:
        if '→' in chapter_range:
            start = chapter_range.split('→')[0].strip().lstrip('第').rstrip('章')
            return int(start) if start.isdigit() else 0
    except ValueError:
        pass
    return 0
