# MuMuPM 优化方案 — 执行计划

> 目标: 基于两次审核（代码质量审核 + PM→漫剧迁移差距分析）的优化方案，经代码库验证后执行。
> 状态: 验证完成 → 进入 Phase 1 执行。

## Goal

完成 P0（安全 + 正确性）与 P1（漫剧能力补齐 + 测试）全部任务；P2 折叠低成本项，架构项记录为 Backlog。

## 验证结论（对原方案的纠正）

| # | 原方案声明 | 验证结果 |
|---|---|---|
| V1 | api_key 明文存储 | ✅ 准确，但**扩展为 3 个敏感列**: `api_key`/`cover_api_key`/`smtp_password`（models/settings.py L17/26/36） |
| V2 | 缺 3 个漫剧 fix handler | ✅ 准确: pm_fix_handlers.py:747-761 注册表仅 `ca_visual_inconsistency` 一个漫剧 handler |
| V3 | 执行器签名 `(db, issue, project_id, user_id, scan_round, decision_log=None)` | ✅ 以 `_fix_visual_inconsistency`(L711) 为模板；原方案签名错误 |
| V4 | PM 巡检按类型过滤 | ✅ 准确: SCAN_REGISTRY 无 domain 字段；项目类型 = `Project.genre`（novel/comic），非 `project_type` 列 |
| V5 | 无漫剧一致性快照 | ✅ 准确: `PMConsistencyState`（pm_consistency_state.py）纯小说章节导向 |
| V6 | 15 处 TODO | ❌ 夸大: 实际 **5 处**真实 TODO（_template_scanner.py:46、cloud_backend.py:137/143、voice_adapter.py:27、midjourney_adapter.py:24）；`_correlation_id_var_dup` 仅 logger.py:174 一处 |
| V7 | 无 API 集成测试 | ✅ 准确: 23 个测试文件，无 tests/api/ |
| V8 | 事件总线缺失漫剧事件 | ✅ 准确: event_bus.py 仅章节事件；ShotStateMachine.transition 为纯函数 |
| V9 | coverage fail_under | ✅ 准确: fail_under=0 |

## 新发现

- **F1**: `_sync_tmp/`（未跟踪）: prod/dev 双版本 pm_scanners/pm_agent/pm。prod 版含 `confidence`/`label`/`DIAG_TYPE_LABELS`/项目级扫描锁，**均未合入线上**。无任何代码引用 → 搁置，不进本次执行范围。
- **F2**: 工作区有未提交 WIP（pm_agent.py、feature_config.py、pm_evolution 等）→ 本次所有实施基于当前工作区状态，**不得**回退/覆盖 WIP。

## 全局约束（Global Constraints）

1. **不提交 commit**（用户未要求）；审查用文件快照 diff（working tree 有 WIP，无法用 commit 区间）。
2. 不得触碰 `_sync_tmp/` 与未提交 WIP 之外的文件；尤其 pm_agent.py 已有 WIP 修改，实施须在其上增量修改。
3. Python 代码: ruff (line-length 120) + mypy；测试用 pytest（asyncio_mode=auto），测试位于 backend/tests/。
4. 代码注释用中文；保持现有项目风格（FastAPI + SQLAlchemy async）。
5. 每个任务必须带测试，实现者自验 `cd backend && python -m pytest <相关测试>`。
6. 数据库变更需提供 Alembic 迁移（backend/migrations/versions/）。
7. 实现者不得自行派发子代理（子代理由编排者统一派发）。
8. 安全: 所有 API Key/密码写入前必须加密；禁止 `as any`/`@ts-ignore`（前端不涉及）；禁止空 catch。

---

## Phase 1 (P0) — 安全与正确性

### Task 1: API Key 加密存储（P0-1）
- **文件**: 新建 `backend/app/core/crypto.py`；改 `backend/app/models/settings.py`、`backend/app/config.py`、`backend/app/main.py`、`backend/.env.example`；新增 `backend/tests/test_settings_crypto.py`
- **Spec**:
  - `crypto.py`: Fernet 封装 `encrypt_api_key(plain)->str` / `decrypt_api_key(cipher)->str`，进程级缓存（dict），从 `get_settings().FERNET_KEY` 取密钥。
  - settings.py: 将 `api_key`/`cover_api_key`/`smtp_password` 列改为私有列 + `@property` getter/setter。getter 兼容旧明文（Fernet InvalidToken → 视为 legacy 明文原样返回）；setter 一律加密。
  - config.py: 新增 `FERNET_KEY: str = ''` 字段。
  - main.py: 启动时若 FERNET_KEY 缺失 → 打印 CRITICAL 告警（fail-closed-on-use：getter/setter 使用时抛 RuntimeError）。
  - .env.example: 增加 `FERNET_KEY=` 说明。
  - 无 schema 变更（Fernet 输出 < 500 字符）。
- **成功标准**: 测试覆盖：加密往返、legacy 明文读取兼容、缺失密钥时读写抛错、缓存命中。`pytest tests/test_settings_crypto.py` 全绿。

### Task 2: 补齐 3 个漫剧 Fix Handler（P0-2）
- **文件**: `backend/app/services/pm/pm_fix_executors.py`、`backend/app/services/pm/pm_fix_handlers.py`、新增 `backend/tests/test_comic_fix_handlers.py`
- **Spec**:
  - ⚠️ **签名纠偏（验证发现）**: `_execute_fix`（pm_fix_handlers.py:268）以旧签名 `handler(issue, project_id, user_id, db) -> str` 统一调用所有 handler（L306）。已注册的 `_fix_visual_inconsistency`（L711）原是 `(db, issue, project_id, user_id, scan_round, decision_log=None)` 且返回 `(bool, str)` tuple——与调用点错位（`scan_round` 无默认值，命中必抛 TypeError），**为既有 bug，本次一并修正为旧签名 + 返回 str**。新 3 个 handler 一律使用旧签名 `(issue, project_id, user_id, db) -> str`。
  - 新增 3 个 executor（建议型，不直接改写用户创作正文，写入 ComicPanel.scene_metadata['pm_fix'] 标记 + 返回建议字符串）：
    - `_fix_scene_discontinuity`（issue_type `ca_scene_discontinuity`）: 场景连续性修复建议（统一为前镜场景描述，字段: conflict_type/scene_from/scene_to/page + entities panel:seq）。
    - `_fix_panel_transition`（issue_type `ca_panel_transition`）: 分镜衔接修复建议（替换中间分镜 camera_angle 打破单调，字段: angle/count + entities panel:seq）。
    - `_fix_dialogue_inconsistency`（issue_type `ca_dialogue_inconsistency`）: 对话语气统一建议（字段: character/style_from/style_to + entities）。
  - 扫描器 issue 经 `ScanIssue.to_dict()`（scanner_base.py:36）后 metadata 字段平铺到 dict 顶层，handler 用 `issue.get(...)` 直接读取。
  - 在 `_register_all_handlers()`（pm_fix_handlers.py:740）specs 元组注册 3 项（裸名，无 pm_agent_ 前缀）。
  - 实现参照既有建议型 executor（`_fix_foreshadow_stale`/`_generate_craft_suggestion`）：缺失字段返回跳过描述；db 异常 try/except 吞掉返回降级描述，不中断主流程。
- **成功标准**: 新增测试 mock db，验证 3 个 handler 注册后可通过 `_FIX_HANDLERS` 命中、`_execute_fix` 执行返回描述字符串、缺字段/db 异常降级、`_fix_visual_inconsistency` 旧签名回归。pytest 全绿。

### Task 3: PM 巡检按项目类型过滤维度（P0-3）
- **文件**: `backend/app/services/pm/pm_scanners.py`、`backend/app/services/pm/pm_agent.py`、`backend/app/config/pm_features.yaml`（如需）、新增测试
- **Spec**:
  - `scan_dimension(name, issue_type, diag_msg_fn, domain='universal')` 增加 `domain` 参数（取值 `novel`/`comic`/`universal`），注册表条目增加 `'domain': domain`。
  - 现存维度标注 domain：character_consistency/foreshadow_age/world_rule_drift/outline_drift/quality_score/paragraph_format → `novel`；comic 4 维（visual/scene/panel/dialogue 走 ScannerAdapter 或直接注册）→ `comic`。**注意**: comic 扫描器通过 `domain_engines/comic/*_scanner.py` 的 BaseScanner 子类接入——需确认注册方式后统一加 domain（引入 `_register_comic_scanners()` 或给 adapters 传 domain）。
  - `_scan_single_project`: 查询 `Project.genre`，过滤 `SCAN_REGISTRY` 中 domain 不匹配的维度（universal 恒跑）。误判降级：genre 查询失败时不过滤（保持现状）。
  - pm_features.yaml 中如有维度级开关同步。
- **成功标准**: 测试：novel 项目不跑 comic 维度、comic 项目不跑 novel 维度、universal 恒跑、未知 genre 全跑（兼容）。现有 test_pm_scanners_integration.py 仍绿。

---

## Phase 2 (P1) — 漫剧能力补齐

### Task 4: 漫剧一致性快照表（P1-1）
- **文件**: 新建 `backend/app/models/pm_consistency_state_comic.py`、`backend/app/models/__init__.py`、`backend/app/services/comic/consistency_guardian.py`、Alembic 迁移、新增测试
- **Spec**: 按原方案表结构（character_visual_states/scene_state/camera_state/forward/backward_consistency_score/global_sequence/episode_id）；在 `ComicConsistencyGuardian.gate_transition` 各 gate 通过后写快照（`_snapshot_after_gate` 辅助方法，异常静默降级）。migrations/versions 新增迁移建表。
- **成功标准**: 迁移可执行；guardian 通过后写快照；测试覆盖快照写入与异常降级。

### Task 5: 漫剧质量评分器（P1-2）
- **文件**: 新建 `backend/app/domain_engines/comic/quality_scorer.py`（或 services/pm 下），接线注册、新增测试
- **Spec**: 6 维评分（visual_diversity/dialogue_density/panel_rhythm/information_density/readability/character_coverage），`BaseScanner` 子类，输出 `ScanIssue(issue_type='ca_quality_low')`，低于阈值报问题。评分数据源: comic_panels + comic_shots + character_cards。
- **成功标准**: 单测覆盖各维度计算与阈值触发；注册进巡检后 `_scan_single_project` 可调用。

### Task 6: TODO/残留清理 + 覆盖率基线（P1-3 + P2-4 折叠）
- **文件**: `_template_scanner.py`、`cloud_backend.py`、`voice_adapter.py`、`midjourney_adapter.py`、`logger.py`、`pyproject.toml`
- **Spec**:
  - `_template_scanner.py:46` 桩代码: 删除该文件（无引用则删）或补实现——先查引用，无引用即删。
  - `cloud_backend.py:137/143`: 加"待接入 Gemini/Anthropic 原生 API"的 Milestone 注释（`# [Milestone]`），不实现。
  - `voice_adapter.py:27`、`midjourney_adapter.py:24`: 标注 Milestone 时间表。
  - `logger.py:174` `_correlation_id_var_dup = True`: 删除孤立变量（先确认无引用）。
  - 覆盖率: 运行 `python -m pytest tests --cov=app --cov-report=term`（backend 下）测量基线；将 `fail_under` 从 0 提升到实测值的整数下限（如实测 <30 则设 30；>60 则设 60），报告实测数字。
- **成功标准**: 无 TODO 残留（保留 Milestone 标注）；pytest 全绿；pyproject fail_under=实测基线。

### Task 7: API 集成测试（P1-4）
- **文件**: 新建 `backend/tests/api/__init__.py`、`conftest.py`（SQLite in-memory fixture）、`test_projects_api.py`、`test_chapters_api.py`、`test_comic_api.py`（分镜/镜头状态流转/审核）、`test_pm_inspection_api.py`
- **Spec**: 用 `httpx.AsyncClient` + ASGITransport 打真实路由；依赖覆盖 `get_db`；覆盖项目 CRUD/章节生成/镜头状态流转（含非法转换 400）/PM 巡检触发。
- **成功标准**: `pytest tests/api/` 全绿；不破坏现有 23 个测试文件。

---

## Phase 3 — 收尾与 Backlog

- 全量 `pytest` + ruff 检查；最终整体审查（oracle，最强调模型）。
- **Backlog（本次不实施，记录 spec）**:
  - B1: 新漫剧扫描器（角色卡覆盖度注：guardian 已做软警告，新扫描器须去重；提示词合规；分镜节奏；画风一致性；审核点完整性已由 `_gate_to_video` 覆盖 → 需聚焦前 2 项）。
  - B2: 事件驱动增量巡检（event_bus 增加 comic.* 事件 + ShotStateMachine 调用点发射 + listener 增量扫描）。
  - B3: 多模态跨镜画风一致性批处理（visual_scanner 增强）。
  - B4: `_sync_tmp/` 处置决策（合并 prod 特性 or 清理）— 需用户决策。

## Rulings（决策记录）

| # | 决策 | 理由 | 代价（若错） |
|---|---|---|---|
| R1 | 本次执行 P0+P1；P2 折叠低成本项(T6 覆盖率)，架构项(B1-B4)留 Backlog | 方案自标 P0=立即/P1=短期；质量优先于摊大饼 | 用户期望全 P2 时需下一轮继续 |
| R2 | 不 commit，用文件快照 diff 审查 | 用户未要求提交 + 工作区 WIP 无法进 worktree | 无 git 记录，靠 ledger+快照恢复 |
| R3 | `_sync_tmp/` 不动 | 未跟踪暂存、无代码引用、prod 特性未定是否合入 | 遗漏 prod 特性 → 已记录 B4 |
| R4 | FERNET_KEY 缺失 → fail-closed-on-use（getter/setter 抛错 + 启动 CRITICAL 警告），非拒绝启动 | 保存存量部署可启动（健康检查等） | 操作者可能忽略警告 → 日志醒目 |
| R5 | 直接在 main 分支工作区实施（不用 worktree） | worktree 不含未提交 WIP，会丢改动 | 实施与 WIP 混杂，审查用快照隔离 |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---|---|
| （暂无） | | |

## Next Step

Task 1（API Key 加密）→ 派发 implementer（snapshot 基线 → 实现 → 报告 → oracle 审查）。