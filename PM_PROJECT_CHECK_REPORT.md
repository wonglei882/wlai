# WLai-PM 全面检查报告

检查时间：2026-08-24
检查范围：backend 全量（app 包 + 3 个入口脚本 + scripts 验证脚本）、README、运行环境
验证方式：全量模块导入测试（隔离 sys.path）、静态依赖分析（AST）、linter 检查

---

## 一、总体结论

| 项目 | 结果 |
|---|---|
| 模块可导入性 | **74 / 76 可直接导入**（2 个失败，同一根因） |
| 静态 lint | 0 错误 |
| 运行时依赖 | Python 3.13.11，fastapi/sqlalchemy/pydantic 等核心依赖已装 |
| 入口可用性 | **不可直接运行**（`models/__init__.py` 为空导致入口脚本 ImportError） |
| 核心代码质量 | 高：设计成体系，边界处理严谨 |

**一句话结论**：PM Agent 核心代码复制完整、质量高，模块级 import 基本全部通过；但存在 **1 个阻断性运行问题**（空 `models/__init__.py`）、**1 个阻断性缺失模块**（`app.models.ooc_violation`）以及一批懒加载的"可选功能"缺失模块，另有 2 个冒烟测试脚本引用了不存在的旧模块名。

---

## 二、项目结构（已核实）

```
wlai-pm/
├── README.md                    # 项目说明（结构描述与实际一致）
├── backend/
│   ├── requirements.txt / .env.example
│   ├── pm_runner.py             # 容器内巡检 runner
│   ├── run_pm_inspection.py     # 单次巡检入口（本地执行）
│   ├── pm_inspector_cron.py     # 巡检定时任务
│   ├── app/
│   │   ├── config.py / database.py / logger.py
│   │   ├── config/pm_features.yaml
│   │   ├── models/              # 27 个模型文件（含 pm_v2/pm_decision_log 等）
│   │   ├── api/                 # pm / pm_control / pm_diagnostic_logs / pm_token_usage
│   │   ├── services/
│   │   │   ├── pm/              # ★ 核心 33 个模块（含 dims/ 3 个评分维度）
│   │   │   ├── ai/ ai_clients/ ai_providers/   # AI 服务链（OpenAI/Gemini/Claude）
│   │   │   ├── core/            # event_bus + event_bus_listeners
│   │   │   ├── guardian/        # OOC 检测 / 连续性 / 伏笔守护
│   │   │   ├── inspiration_sub/ # skill_template / skill_system / diagnostic
│   │   │   ├── memory_service.py / proactive_reporter.py / proactive_suggestions.py / json_helper.py
│   │   ├── agent/
│   │   │   ├── core/command_registry.py
│   │   │   └── domain/odd_config.py + tools/（10 个 PM 命令模块）+ infrastructure/text_analysis.py
│   │   └── core/json_utils.py
│   └── scripts/                 # smoke_import / smoke_import2 / check_deps
└── 未复制部分（符合 README）：main.py、alembic 迁移、测试、前端
```

---

## 三、导入验证结果（实测）

**测试方法**：`sys.path.insert(0, backend)` 强制解析本工作区代码，批量 import 76 个模块。

```
TOTAL=76  OK=74  FAIL=2
```

**2 个失败（同一根因）**：

| 模块 | 原因 |
|---|---|
| `app.services.guardian.long_novel_guardian` | `ModuleNotFoundError: No module named 'app.models.ooc_violation'` |
| `app.services.guardian.ooc_detector` | 同上（顶层 import，非懒加载） |

> `ooc_detector.py` 内部已定义业务值对象 `OOCViolation`（dataclass），但顶层 `from app.models.ooc_violation import OOCViolation as OOCModel` 引用的是 SQLAlchemy 持久化模型，**必须补建**。

**⚠️ 环境陷阱（重要）**：本机存在 `pip install -e` 的 `novelforge-0.1.0` editable 包，其 finder 将 `app` 解析到旧路径 `D:\novelforge\novelforge-master\backend\app`。**在未显式插入 backend 路径时导入 `app.*` 测到的是旧项目代码**，会产生假性结果。后续任何测试都必须显式 `sys.path.insert(0, backend)`（现有 3 个 scripts 已内置此逻辑，正常）。

---

## 四、问题清单

### 🔴 P0 阻断性问题（必须修复才能运行）

| # | 问题 | 影响 | 位置 |
|---|---|---|---|
| 1 | `models/__init__.py` 为空文件 | `from app.models import Project` 抛 `ImportError`，**`run_pm_inspection.py:25` 主入口运行即失败**；`run_pm_inspection.py:27` 随后使用 `Project.id` 也会挂 | `backend/app/models/__init__.py` |
| 2 | `app.models.ooc_violation` 缺失 | `guardian` 两个模块（长期守护链）无法导入 | 需补模型文件 |

### 🟡 P1 懒加载缺失模块（导入不报错，运行到对应功能时报错）

均为函数内 `import`，不影响模块加载，但触发功能即失败：

| 缺失模块 | 被谁引用 | 功能 |
|---|---|---|
| `app.models.narrative_structure` | `pm_write_diagnose.py` | 大纲结构诊断 |
| `app.models.relationship` | `pm_write_diagnose.py` / `event_bus_listeners.py` | 关系网分析 |
| `app.services.core.mcp_tools_loader` | `ai_service.py` | 用户 MCP 工具加载 |
| `app.services.inspiration_skills` | `pm_sequence.py` / `pm_consistency.py` / `event_bus_listeners.py` | 技能库（⚠️ 疑似被拆入 `inspiration_sub/` 后调用方未同步） |
| `app.services.inspiration_sub.auto_skill` | `skill_system.py` | 自动技能生长 |
| `app.services.inspiration_sub.proactive_session` | `skill_system.py` | 主动会话 |
| `app.services.project_manager_service` | `api/pm.py` | 旧版 PM 命令（疑似历史残留） |
| `app.services.quality_forecast` | `event_bus_listeners.py` | 质量预测 |
| `app.agent.core.command_executor` | `api/pm.py` | 命令执行器 |
| `app.agent.infrastructure.progress_analyzer` | `pm_write_diagnose.py` | 进度趋势分析 |
| `app.utils.redis_client` | `api/pm_control.py` | Redis（有 try/except 兜底，最轻） |

### 🟡 P2 冒烟测试脚本引用错误（脚本自身 bug）

| 脚本 | 引用了不存在的模块 | 应为 |
|---|---|---|
| `scripts/smoke_import.py:29` | `app.services.pm.pm_decision_metrics` | `app.services.pm.pm_metrics` |
| `scripts/smoke_import2.py:24` | `app.agent.domain.tools.pm_knowledge` | 现存 tools 中对应模块（复制时已合并/改名） |

导致 README 声称"冒烟测试通过"与实际脚本输出（各有 1 FAIL）不符。

### ⚪ 说明项（非问题，符合 README 声明）
- 无 `main.py`（FastAPI 应用入口）、无 alembic 迁移、无测试 → 均为"未复制"范围
- `app.services.pm.__init__.py` 正常导出 7 个核心符号，无异常

---

## 五、核心模块质量评估（通读结论）

| 模块 | 评价 |
|---|---|
| `pm_agent.py`（39.5KB） | 巡检主循环完整：事件触发→扫描→决策→修复→验证→记忆沉淀，状态机清晰 |
| `pm_agent_decision.py` | 诊断→决策→修复→验证闭环，含降级/重试策略 |
| `pm_scanners.py` | `@scan_dimension` 注册 6 大巡检维度（角色一致性/伏笔老化/世界观漂移/大纲漂移/质量评分/段落格式），可插拔设计 |
| `pm_fix_handlers.py` | 修复处理器注册表 + 条件约束 + 状态回滚，设计严谨 |
| `pm_metrics.py` | 决策指标统计（替代原 `pm_decision_metrics` 的新命名） |
| `command_registry.py` | 命令注册/派发系统，10 个 PM 工具模块均接入 |
| 其余 30+ 模块 | 普遍具备 try/except 兜底、懒加载防循环依赖、日志完整 |

代码风格统一、注释到位、异常路径处理充分，属高质量复制。

---

## 六、修复建议（按优先级）

1. **重建 `models/__init__.py`**：显式导出全部 27 个模型（`from app.models.project import Project` 等），一行修复入口 ImportError。
2. **补 `app/models/ooc_violation.py`**：参考 `ooc_detector.py` 中 `OOCViolation` 值对象字段 + 现有模型风格，建 SQLAlchemy 表模型。
3. **修 smoke 脚本 2 处引用**：`pm_decision_metrics` → `pm_metrics`；`pm_knowledge` 替换为实际模块（如 `pm_consistency`）。
4. **对齐 `inspiration_skills` 与 `inspiration_sub`**：要么在 `inspiration_sub/__init__.py` 提供 `inspiration_skills` 兼容导出，要么更新 3 个调用方 import。
5. **懒加载缺失模块**：若为业务模块，从源项目补复制；若已弃用（如 `project_manager_service` 旧版命令），清理引用点。
6. **运行验证**：修复后执行 `python scripts/smoke_import.py`、`smoke_import2.py` 应全绿，再在配置好 PostgreSQL 后用 `python backend/run_pm_inspection.py` 做端到端验证。

---

## 七、验证脚本清单（原文保留）

```bash
cd backend
python ../scripts/smoke_import.py    # PM 核心模块导入测试
python ../scripts/smoke_import2.py   # AI/agent/api 模块导入测试
python ../scripts/check_deps.py      # 静态检查缺失的 app.* 依赖
```
