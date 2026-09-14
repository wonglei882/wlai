# Findings — 方案验证研究记录

## 代码库结构要点（验证任务用）

- **PM 巡检链路**: `pm_agent.py:_scan_single_project`（L128）→ 遍历 `pm_scanners.py:SCAN_REGISTRY`（L70）→ `meta['fn'](db, project_id, user_id)` → 写 diagnostic_log → `diagnose_and_fix`（pm_agent_decision）。
- **修复注册表**: `pm_fix_handlers.py:_register_all_handlers`（L740）specs 元组 `(裸名, pm_agent_前缀名, handler, 描述)`；`_FIX_HANDLERS[prefix]=(handler, desc)`。comic 仅 `ca_visual_inconsistency`（L760）。
- **执行器模式**: `pm_fix_executors.py` 9 个 novel executor，签名 `(issue, project_id, user_id, db)->str`；但 `_fix_visual_inconsistency`（handler 内联于 pm_fix_handlers.py:711）签名 `(db, issue, project_id, user_id, scan_round, decision_log=None)` —— 新 comic executor 照此写。
- **扫描器注册**: novel 维度用 `@scan_dimension` 装饰器（pm_scanners.py:73，无 domain 参数）；comic 4 维是 `BaseScanner` 子类（domain_engines/comic/visual|scene|panel|dialogue_scanner.py，issue_type: ca_visual_inconsistency/ca_scene_discontinuity/ca_panel_transition/ca_dialogue_inconsistency）；`scanner_base.py` 提供 `ScannerAdapter` 用于裸函数兼容。
- **project 类型**: `Project.genre`（project.py），前端取值 novel/comic。无 project_type 列。
- **敏感列**: models/settings.py — api_key(L17)/cover_api_key(L26)/smtp_password(L36) 均 VARCHAR(500) 明文。
- **配置**: config.py `Settings`（pydantic），`settings = Settings()` L153；.env.example 位于 backend/。
- **一致性守护**: consistency_guardian.py `ComicConsistencyGuardian`（L66）单例 `get_comic_guardian()`；gate_transition 按 target_status 分派 3 个 gate + gate_storyboard_confirm 批量门控；`_check_dialogue_style` 产出 `ca_dialogue_inconsistency`；视觉门控回写 `shot.last_consistency_score`。
- **小说快照**: pm_consistency_state.py `PMConsistencyState`（project+chapter 唯一约束），字段 character_states/world_states/foreshadow_status/character_arc_progress。
- **事件总线**: event_bus.py 单例，章节类事件；ShotStateMachine.transition 纯静态（无事件发射）。
- **测试**: backend/tests/ 23 个文件；pyproject `[tool.pytest.ini_options] asyncio_mode="auto" testpaths=["tests"]`（注意 testpaths 相对 rootdir）；coverage source=["app"] fail_under=0。
- **TODO 真伪**: 真实 5 处（_template_scanner.py:46、cloud_backend.py:137/143、voice_adapter.py:27、midjourney_adapter.py:24）；logger.py:174 `_correlation_id_var_dup = True` 孤立变量；json_helper.py:268/skill_system.py:276/prompt_compiler.py:220 为文档假阳性。

## 关键断言（F1/F2）

- `_sync_tmp/` 未跟踪、无代码引用；prod 版 pm_scanners/pm_agent 含未合入特性（DIAG_TYPE_LABELS、confidence、项目级锁）。→ 处置待 B4 决策。
- 工作区 WIP: `git status` 显示 M backend/app/api/pm.py、M config/pm_features.yaml、M models/__init__.py、M services/pm/feature_config.py、M services/pm/pm_agent.py、前端若干 + ?? _sync_tmp/、pm_evolution 相关。→ 实施基于当前磁盘状态，禁止 revert。