# MuMuPM-Project

从 `MuMuAINovel-main` 提取的 **PM Agent（项目主管 Agent）独立后端模块**，用于代码研究与重构。

## 项目结构

```
D:\ai\MuMuPM-Project\
├── backend\
│   ├── requirements.txt          # Python 依赖
│   ├── .env.example              # 环境变量模板
│   ├── pm_runner.py              # PM 主动巡检 runner（对所有项目巡检并记日志）
│   ├── run_pm_inspection.py      # 单次巡检入口
│   ├── pm_inspector_cron.py      # 巡检定时任务
│   ├── app\
│   │   ├── config.py             # Settings（环境配置）
│   │   ├── database.py           # SQLAlchemy 异步数据库
│   │   ├── logger.py             # 日志
│   │   ├── config\
│   │   │   └── pm_features.yaml  # PM 功能开关（核心/可选/批处理分级）
│   │   ├── models\               # 数据模型（pm_* 系列 + 业务模型）
│   │   ├── api\
│   │   │   ├── pm.py             # PM 主 API
│   │   │   ├── pm_control.py     # PM 启停/暂停/健康
│   │   │   ├── pm_diagnostic_logs.py  # 诊断日志 API
│   │   │   └── pm_token_usage.py      # token 用量 API
│   │   ├── services\
│   │   │   ├── pm\               # ★ PM Agent 核心（33 个模块）
│   │   │   │   ├── pm_agent.py           # 巡检主循环
│   │   │   │   ├── pm_agent_decision.py  # 诊断→决策→修复→验证闭环
│   │   │   │   ├── pm_scanners.py        # 巡检维度注册表（@scan_dimension）
│   │   │   │   ├── pm_fix_handlers.py    # 修复处理器注册表
│   │   │   │   ├── pm_fix_executors.py   # 修复执行器
│   │   │   │   ├── self_evolve.py        # 自进化（技能生长/自评/经验库）
│   │   │   │   ├── self_tuning.py        # 自调参（贝叶斯成功率）
│   │   │   │   ├── memory.py             # PMMemoryV2 经验记忆
│   │   │   │   ├── quality_scorer.py     # 质量评分
│   │   │   │   ├── pm_preference_learner.py  # 偏好学习
│   │   │   │   ├── pm_consistency_guardian.py # 一致性守护
│   │   │   │   └── dims\                 # 可插拔评分维度
│   │   │   ├── ai\               # AI 服务（ai_service / config / metrics）
│   │   │   ├── ai_clients\       # AI 客户端（OpenAI/Gemini/Claude）
│   │   │   ├── ai_providers\     # AI 供应商适配
│   │   │   ├── core\             # 事件总线（event_bus / listeners）
│   │   │   ├── guardian\         # 长篇守护（OOC/连续性/伏笔）
│   │   │   ├── json_helper.py    # 宽松 JSON 解析
│   │   │   ├── proactive_reporter.py    # 主动预警报告
│   │   │   ├── proactive_suggestions.py # 主动建议
│   │   │   └── memory_service.py # 长期记忆（向量）
│   │   ├── agent\
│   │   │   ├── core\command_registry.py # 命令注册表
│   │   │   └── domain\
│   │   │       ├── odd_config.py
│   │   │       └── tools\        # ★ PM 工具集（10 个命令模块）
│   │   └── core\json_utils.py
│   └── scripts\                  # 依赖检查/冒烟测试脚本
└── ...
```

## PM Agent 核心模块关系

```
事件总线(event_bus) ──触发──> pm_agent.py(巡检主循环)
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
    pm_scanners.py     pm_agent_decision.py   proactive_reporter.py
    (6大巡检维度)        (诊断→决策→修复→验证)    (主动预警报告)
              │               │
              ▼               ▼
    dims/quality_score   pm_fix_handlers.py
    dims/paragraph_format  └─ pm_fix_executors.py
```

## 说明

- **复制范围**：仅 PM 后端模块（services/pm + 相关 api/models/services 依赖）。
- **验证状态**：PM 核心 33 个模块 + AI 服务链 + agent 工具集 + 4 个 PM API 已通过 import 冒烟测试。
- **未复制**：前端、`main.py` 应用入口、数据库迁移（alembic）、测试。
- **运行前提**：需要 PostgreSQL（按 `.env.example` 配置 `DATABASE_URL`），以及 AI 模型 API key。

## 验证脚本

```bash
cd backend
python ../scripts/smoke_import.py    # PM 核心模块导入测试
python ../scripts/smoke_import2.py   # AI/agent/api 模块导入测试
python ../scripts/check_deps.py      # 静态检查缺失的 app.* 依赖
```
