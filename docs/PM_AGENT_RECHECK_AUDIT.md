# PM Agent 优化后复核评估报告

> 评估对象：`backend/app/services/pm/`（PM Agent 核心链路）
> 基线：`docs/PROJECT_MULTI_DIMENSION_AUDIT.md`（2026-08-25 首轮 10 维评估）
> 方法：逐文件精读 + pyflakes 静态扫描 + 全量 pytest + 消费者链路核对
> 日期：2026-08-25

---

## 一、总评分卡（对比首轮）

| # | 维度 | 首轮 | 本轮 | 变化 | 一句话结论 |
|---|---|---|---|---|---|
| 1 | 架构与分层 | 8.5 | **9.0** | +0.5 | 公共门面 + 状态单例，边界大幅收敛 |
| 2 | 代码质量 | 9.0 | **9.2** | +0.2 | 死代码再清理 20 行；仅剩 unused-import 级告警 |
| 3 | 性能与资源 | 8.5 | 8.5 | — | 无变化 |
| 4 | 可靠性/健壮性 | 8.5 | 8.5 | — | 无变化 |
| 5 | 可观测性 | 8.0 | **8.5** | +0.5 | `record_scan` 埋点已接线 |
| 6 | 安全 | 7.5 | 7.5 | — | 无变化 |
| 7 | 可维护性 | 7.5 | **8.0** | +0.5 | `pm_agent` 869→720 行，退出超长名单 |
| 8 | 测试覆盖 | 7.5 | 7.5 | — | 65 用例全通过（保持） |
| 9 | 文档 | 8.0 | 8.0 | — | 无变化 |
| 10 | 技术债务 | 7.0 | **8.0** | +1.0 | 5 项债务已清偿，余 4 项低危 |

**综合评级：B+ → A-（结构性问题基本清零，进入"打磨残留"阶段）**

---

## 二、上一轮 5 项优化——逐项落地验证

### ✅ 1. P0 全局状态收拢（`PMRuntimeState` 单例）

- `pm_runtime_state.py`（56 行）：集中 `consecutive_idle_rounds / last_round_stats / last_round_degraded_count / last_daily_summary / last_round_chapter_counts / last_scan_at / pm_agent_task / loop_crash_count` 等全部运行时状态。
- `pm_agent.py` 内 **27 处** 状态读写全部切换为 `runtime_state.xxx`，模块级可变变量与 `global` 声明归零（首轮 8 变量 + 9 global）。
- 收益：测试可整体复位状态；多实例/多入口共享同一状态视图。

### ✅ 2. P1 公共 API 门面（`pm_api.py`）

- 30 行门面 + `__all__` 白名单（`scan_all_projects / diagnose_and_fix / register_pm_agent / stop_pm_agent / get_pm_health / register_pm_handlers`）。
- 两个 API 路由已切换：`api/pm.py:203` 与 `api/pm_control.py:275` 均从 `pm_api` 导入。
- 外部依赖面从"任意内部符号"收敛为"6 个稳定符号"，后续内部拆分不再引发外部 import 漂移。

### ✅ 3. P1 死代码再导出清理（`pm_agent_decision`）

- `pm_agent_decision.py` 664 → **593 行**，删除为不存在 `tests/unit` 服务的兼容再导出约 20 行。
- 复核残留：`classify_severity_by_type` 与 `_decompose_repair_priority` 的再导出**仍被消费**（`pm_agent.py:36`、`pm_agent.py:173`），保留正确；`_rule_based_sort` 再导出无消费者（测试直接导自 `pm_decision_helpers`），为漏网死代码（见 §五）。

### ✅ 4. P3 魔法数字配置化

`pm_features.yaml` 中已实际存在并被代码读取：

```yaml
decompose_threshold: 3       # LLM 排序阈值（pm_agent.py）
cleanup_every_rounds: 48     # 日志清理周期
max_auto_fix_attempts: 3     # 近7天同类修复上限
idle_threshold_rounds: 2     # 空闲降频触发
idle_interval_multiplier: 4  # 降频倍数
similarity_threshold: 0.8    # 自进化经验合并阈值
decay_half_life_days: 30     # 经验衰减半衰期
```

- 核对 `pm_agent.py` / `pm_agent_decision.py` / `self_evolve.py` 均为 `pm_feature_config.get_xxx()` 读取，**非残留常量**。
- 残余硬编码常量：`FAILED_COOLDOWN_HOURS=24` / `ENV_FAILED_COOLDOWN_MINUTES=10`（`pm_fix_handlers.py`）——有注释说明，属可接受的模块级常量（非魔法数字），列低优先级。

### ✅ 5. P4 metrics 埋点接线（`record_scan`）

- `pm_agent.py:257-271`：每轮巡检后调用 `_metrics.record_scan(scanned_projects, total_issues, elapsed_s)`，异常非阻塞降级。
- 首轮"已定义从未调用"的缺口闭合，巡检指标正式可观测。

---

## 三、质量门禁实测（非估算）

| 检查 | 结果 |
|---|---|
| pytest 全量 | **65 tests collected / 全部通过**（4.00s 收集） |
| pyflakes `app/` | **30 条告警，全部为 unused-import**（0 未定义 / 0 真错误） |
| 编译完整性 | 上轮 compileall 通过，本轮改动均为增删改小范围 |
| 运行态 import | `scan_all_projects / register_pm_agent / get_pm_health / diagnose_and_fix` 链路可导入 |

---

## 四、核心模块当前规模（全部 < 800 行目标线）

| 文件 | 行数 | 职责 |
|---|---|---|
| `pm_agent.py` | 720 | 主循环 / 调度 / 健康（869 → **720**，退出超长名单） |
| `pm_agent_decision.py` | 593 | 诊断 → 修复编排（664 → **593**） |
| `pm_fix_handlers.py` | 587 | 修复处理器注册表 |
| `self_tuning.py` | 592 | 失败后验调参 |
| `pm_decision_helpers.py` | 524 | 决策辅助（LLM 降级链） |
| `pm_scanners.py` | 520 | 7 维巡检扫描器 |

> 全 `pm/` 33 个文件无 >800 行者；项目级超长文件（>700）由首轮 6 个减至 5 个，剩余均在 `services/` 其他子域（foreshadow 1047 / memory_service 987 / ai_service 890 / event_bus_listeners 768 / pm_consistency 711），与 PM Agent 核心链路无关。

---

## 五、本轮新发现（残留低危问题）

### P2｜`pm/__init__.py` 7 个顶层再导出为死代码

```python
from app.services.pm.memory import PMMemoryV2 as PMMemory  # noqa: F401
from app.services.pm.quality_scorer import PMQualityScorerV2 as PMQualityScorer  # noqa: F401
# ... 共 7 个
```

- 全库检索 `from app.services.pm import X`：**0 个消费者**（唯一命中为 `dims/__init__.py` 内部相对引用）。
- 上轮只清了 `pm_agent_decision` 的再导出，**漏了 `__init__.py`**。属"为假设中的外部消费者留门"，YAGNI 死代码。

### P3｜`pm_agent_decision.py:64` `_rule_based_sort` 再导出无消费者

- 消费者核对：测试直接 `from pm_decision_helpers import _rule_based_sort`，无经 `pm_agent_decision` 的路径 → 可删。

### P3｜`pm_agent.py:37` 导入未用符号

- `from app.services.pm.pm_runtime_state import PMRuntimeState, runtime_state` 中 `PMRuntimeState` 类名未直接使用（仅用实例 `runtime_state`），可精简为单符号导入。

### P3｜`_MAX_CRASH_RESTART = 3`

- 主循环崩溃重启上限仍为模块常量，若追求全配置化可入 yaml（收益低，可不做）。

---

## 六、尚未清偿的债务（首轮遗留）

| 优先级 | 债务项 | 现状 |
|---|---|---|
| P1 | 5 个超长文件（非 pm 核心域） | 部分清偿：`event_bus_listeners`(768) 已拆为 4 领域模块（commit `0f8e7c1`） |
| P2 | 三个入口脚本去重 | 已清偿：统一 `pm_inspection_runner.py`，三旧入口转薄壳（commit `0f8e7c1`） |
| P2 | provider 错误处理逐家校对（openai/anthropic/gemini） | 已清偿：anthropic/gemini 补齐递归深度保护，对齐 openai（commit `0f8e7c1`） |
| P2 | DB 集成测试 + scanner 诊断器测试 | 已清偿：scanner 纯逻辑测试（`test_scanner_utils.py`，+12）+ DB 集成测试（`test_pm_scanners_integration.py` 9 cases + `test_pm_proactive_inspection_integration.py` 7 cases，sqlite 内存库基建） |

---

## 六-A、§五 残留清偿执行记录（2026-08-25，commit `5ec943a`）

§五 所列 4 项残留全部执行完毕：

| 项 | 处置 | 验证 |
|---|---|---|
| `__init__.py` 7 个死再导出（P2） | 删除，docstring 注明清理原因 | 全库 grep 0 消费者 |
| `_rule_based_sort` 再导出（P3） | 从 `pm_agent_decision` 删除 | 消费者核对：仅测试经 `pm_decision_helpers` 直达 |
| `pm_agent.py:37` 冗余导入（P3） | 精简为 `import runtime_state` | pyflakes F401 消除 |
| `_MAX_CRASH_RESTART`（P3） | 配置化入 yaml `performance.max_crash_restart` | import 冒烟 = 3 |

**执行后门禁**：
- pytest：**65 passed**（无回归）
- pyflakes `app/services/pm/`：由 13 条降至 **2 条**，且均为 §五 判定"保留正确"的有消费者再导出（`classify_severity_by_type` / `_decompose_repair_priority`，实际由 `pm_agent.py:36,173` 消费，非死代码）。
- import 冒烟：`app.services.pm` / `pm_agent` / `pm_agent_decision` 正常加载。

---

## 七、结论

1. **五项优化全部真实落地**，且有运行态与测试证据支撑，非纸面改动。
2. **结构性问题清零**：全局状态、公共边界、死代码、魔法数字、指标盲区五项 P0/P1 债务已解除。
3. **§五 残留已全部清偿**（commit `5ec943a`），pyflakes 仅剩 2 条有消费者再导出（设计保留）。
4. **风险点**：`__init__.py` 与 `_rule_based_sort` 死代码删除前已 grep 确认全库 0 消费者，删除后 65 测试通过无回归。

*评估方法说明：全部量化数据来自本轮实机静态扫描（pyflakes 全库）与全量 pytest，非估算。*

---

## 六-B、§六 债务清偿执行记录（2026-08-25，commit `0f8e7c1`）

### P1｜`event_bus_listeners`(768) 拆分 ✅

按领域拆为 4 个单一职责模块 + 主文件薄壳：

| 模块 | 行数 | 职责 |
|---|---|---|
| `event_bus_listeners.py` | ~240 | 6 个监听器薄壳 + 注册函数 + 兼容再导出 |
| `event_bus_listeners_analysis.py` | ~55 | 章节生成后自动分析 |
| `event_bus_listeners_consistency.py` | ~120 | 一致性检查 + 延迟调度 + 即时巡检 |
| `event_bus_listeners_foreshadow.py` | ~175 | 伏笔状态自动回写/回收 |
| `event_bus_listeners_relationships.py` | ~165 | 关系网自动更新 |

- 主文件保留 `_auto_run_consistency_check` 兼容再导出（`pm_fix_executors.py` 消费，pyflakes 1 条 F401 为设计保留）
- 顺带修复**原参序 bug**：`pm_fix_executors.py` 调用 `_auto_run_consistency_check(project_id, chapter_id, user_id, db)` 与签名 `(db, chapter_id, project_id, user_id)` 错位，已修正并加注释防回退

### P2｜三个入口脚本去重 ✅

`run_pm_inspection.py` / `pm_runner.py` / `pm_inspector_cron.py` 逻辑完全重叠（同表查询 + 同巡检函数 + 同阈值分级），合并为统一入口 `pm_inspection_runner.py`：
- 参数化 `--log-dir`（默认 backend/logs，`pm_runner` 传 `/app/logs`，cron 传 `""` 仅控制台）
- 三旧文件保留为薄壳转发（兼容既有 cron / docker exec 引用路径）

### P2｜provider 错误处理逐家校对 ✅

校对发现 anthropic/gemini 与 openai 的 `_generate_with_tools` 不一致：
- **openai（基准）**：递归时 `tools=None` + `recursion_depth` 上限 2 层
- **anthropic/gemini（修复前）**：递归仍传 `tools`，且无深度保护 → 存在无限工具循环风险
- 修复：三家对齐 `recursion_depth: int = 0` + `max_depth = 2` + 递归禁传工具

### P2｜DB 集成测试 + scanner 诊断器测试 ⏳ 部分

- ✅ 新增 `tests/test_scanner_utils.py`（+12 cases）：`_safe_json_loads` / `_extract_chapter_from_range` / `SCAN_REGISTRY` 完整性守卫
- ⏳ DB 集成测试：仍需要测试库基建（当前 conftest 无测试库 fixture），保留待办

**执行后门禁**：pytest **77 passed**（+12）；改动文件 pyflakes 全部 clean（仅 event_bus_listeners 1 条设计保留的兼容再导出）。

---

## 六-C、DB 集成测试清偿记录（2026-08-25，commit 待提交）

### 测试库基建

`tests/conftest.py` 新增 `db_session` fixture：
- `sqlite+aiosqlite://` 内存库 + `StaticPool`（单连接防 :memory: 数据丢失）
- `__import__('app.models')` 注册全部模型 → `Base.metadata.create_all` 建表
- 历史遗留兼容：`characters.main_career_id` 引用无模型的 `careers` 表，注册占位表供外键解析
- `pytest.ini`：`asyncio_mode = auto`（pytest-asyncio 1.3.0）

### 新增集成测试（+16 cases）

| 文件 | 覆盖 |
|---|---|
| `test_pm_scanners_integration.py`（9） | `_scan_character_consistency` 硬阈值跳变/无跳变；`_scan_foreshadow_age` 超龄/新鲜；`_scan_world_rule_drift` hash 漂移>50%/相同；`_scan_paragraph_format` 超长段落/正常；`_write_diagnostic_from_scan` upsert |
| `test_pm_proactive_inspection_integration.py`（7） | 健康项目 10.0；低质量 critical→3.0 / warning→5.0；失败模式→7.0；world drift→8.0；多问题取最低分；项目隔离 |

### 验证

- pytest：**93 passed**（+16 集成）
- 新增文件 pyflakes 全部 clean
- 测试全部走真实 sqlite 内存库 + 真实模型写入/查询，覆盖巡检阈值分级、扫描器查库逻辑、诊断 upsert 三块此前无自动化覆盖的链路
