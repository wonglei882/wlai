# WLai

**AI 内容一致性守护平台 + AI 漫剧制片**

两大产品线：
1. **ConsistencyAgent** — 通用内容一致性守护（长篇小说 + 漫剧），检测并修复 AI 生成内容中的一致性问题
2. **ComicProductionAgent** — AI 漫剧制片流水线（设定圣经 → 分镜 → 提示词编译 → 素材管理 → 审核 → 合成）

核心原则：**让 AI 不敢乱来**（外置记忆 + 提示词编译 + 人工审核 + 反馈闭环）

---

## 快速开始（Docker 一键部署）

### 系统要求

- Docker 20+ 和 Docker Compose v2+
- 4GB+ 内存
- AI 提供商 API Key（OpenAI / Anthropic / Gemini）

### 3 步启动

```bash
# 1. 克隆项目
git clone <repo-url> && cd WLai

# 2. 运行启动脚本（首次会引导配置 .env）
#    Linux/Mac:
bash start.sh
#    Windows:
.\start.ps1

# 3. 编辑 .env 填入 API Key 后再次运行启动脚本
```

启动后访问：
- **前端界面**: http://localhost:3000
- **后端 API**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs

### 手动 Docker 部署

```bash
cp backend/.env.example .env
# 编辑 .env 填入 OPENAI_API_KEY 等配置
docker compose up -d
```

---

## 项目结构

```
frontend\                        # ★ Next.js 前端
├── src/
│   ├── app/                     # App Router 页面
│   ├── components/              # UI 组件 (shadcn/ui)
│   ├── lib/                     # API 客户端 + 工具函数
│   ├── store/                   # Zustand 状态管理
│   └── types/                   # TypeScript 类型定义
├── Dockerfile
└── package.json
backend\                         # FastAPI 后端
├── requirements.txt              # Python 依赖
├── requirements-full.txt         # 重依赖（向量库/ML/NLP/可视化）
├── .env.example                  # 环境变量模板
├── alembic.ini                   # Alembic 迁移配置
├── migrations\                   # 数据库迁移（含初始 schema）
├── pm_runner.py                  # PM 主动巡检 runner
├── run_pm_inspection.py          # 单次巡检入口
├── pm_inspector_cron.py          # 巡检定时任务
├── app\
│   ├── main.py                   # FastAPI 应用入口
│   ├── config.py                 # Settings（环境配置）
│   ├── database.py               # SQLAlchemy 异步数据库
│   ├── logger.py                 # 日志
│   ├── config\
│   │   └── pm_features.yaml      # 功能开关（PM/一致性Agent/漫剧制片）
│   ├── models\                   # 数据模型（40+ 张表）
│   │   ├── pm_*.py               # PM Agent 模型
│   │   ├── content_segment.py    # 通用内容片段（多模态）
│   │   ├── comic.py              # 漫剧分镜 + 视觉参考
│   │   ├── comic_bible.py        # 设定圣经/角色卡/画风卡/负面词库/集数
│   │   ├── comic_shot.py         # 分镜表/镜头/素材
│   │   ├── comic_review.py       # 人工审核点
│   │   └── webhook.py            # Webhook 回调配置
│   ├── adapters\                 # ★ 内容适配器层
│   │   ├── base.py               # ContentAdapter ABC + 注册表
│   │   ├── novel_adapter.py      # 网文适配器
│   │   └── comic_adapter.py      # 漫剧适配器
│   ├── api\
│   │   ├── pm.py                 # PM 主 API
│   │   ├── pm_control.py         # PM 启停/暂停/健康
│   │   ├── pm_diagnostic_logs.py # 诊断日志 API
│   │   ├── pm_token_usage.py     # token 用量 API
│   │   └── v1\                   # ★ API v1（通用 Agent + 漫剧制片）
│   │       ├── content.py        # 内容推送 /api/v1/content/*
│   │       ├── reports.py        # 一致性报告 /api/v1/reports
│   │       ├── webhooks.py       # Webhook 管理 /api/v1/webhooks
│   │       ├── comic_bible.py    # 设定圣经/角色卡/画风卡/负面词/集数
│   │       └── comic_storyboard.py # 分镜/镜头/素材/审核
│   ├── domain_engines\           # ★ 领域引擎
│   │   ├── novel\                # 长篇小说（复用 pm_scanners）
│   │   └── comic\                # 漫剧（4 个扫描维度）
│   │       ├── visual_scanner.py     # 角色视觉一致性
│   │       ├── scene_scanner.py      # 场景连续性
│   │       ├── panel_scanner.py      # 分镜衔接
│   │       └── dialogue_scanner.py   # 对话气泡一致性
│   ├── services\
│   │   ├── pm\                   # ★ PM Agent 核心（37 个模块）
│   │   │   ├── pm_agent.py           # 巡检主循环
│   │   │   ├── pm_agent_decision.py  # 诊断→决策→修复→验证闭环
│   │   │   ├── pm_scanners.py        # 巡检维度注册表
│   │   │   ├── pm_fix_handlers.py    # 修复处理器（含反馈回路）
│   │   │   ├── scanner_base.py       # BaseScanner 基类 + ScanIssue
│   │   │   ├── pipeline.py           # 5 阶段流水线抽象
│   │   │   ├── fix_pipeline.py       # FixChain 组合编排
│   │   │   ├── self_evolve.py        # 自进化
│   │   │   ├── self_tuning.py        # 自调参 + 策略选择
│   │   │   └── dims\                 # 可插拔评分维度模板
│   │   ├── comic\                # ★ 漫剧制片服务
│   │   │   ├── shot_state_machine.py  # 镜头状态机（7 状态）
│   │   │   ├── prompt_compiler.py     # 提示词编译器（MJ/SD/即梦/可灵）
│   │   │   └── storyboard_gen.py      # 分镜生成器（规则版）
│   │   ├── ai\                   # AI 服务
│   │   ├── ai_clients\           # AI 客户端（OpenAI/Gemini/Claude）
│   │   ├── ai_providers\         # AI 供应商适配
│   │   ├── core\                 # 事件总线
│   │   └── guardian\             # 长篇守护
│   └── agent\                    # PM 命令执行与工具集
└── scripts\                      # 运维脚本
```

---

## 架构总览

```
┌─────────────────────────────────────────────────────────┐
│              API Layer                                   │
│  /api/v1/content/*   — 内容推送（通用）                  │
│  /api/v1/reports     — 一致性报告                        │
│  /api/v1/webhooks    — Webhook 回调                      │
│  /api/v1/comic/*     — 漫剧制片（圣经/分镜/镜头/审核）    │
│  /api/pm/*           — PM Agent（向后兼容）               │
├─────────────────────────────────────────────────────────┤
│              Service Layer                               │
│  ConsistencyAgent    — 巡检→诊断→修复→验证闭环           │
│  ComicProduction     — 分镜生成→提示词编译→状态流转       │
│  PromptCompiler      — 角色卡+画风卡 → 多平台提示词       │
│  ShotStateMachine    — 7 状态镜头流水线                   │
├─────────────────────────────────────────────────────────┤
│              Domain Engines                              │
│  NovelEngine (6维)   — 角色/伏笔/世界观/大纲/质量/段落    │
│  ComicEngine (4维)   — 视觉/场景/分镜/对话               │
├─────────────────────────────────────────────────────────┤
│              Data Layer (40+ 张表)                       │
│  PM 模型 + ContentSegment + ComicBible/Shot/Review       │
└─────────────────────────────────────────────────────────┘
```

---

## 漫剧制片流水线

以「镜头」为最小单位，7 状态流转：

```
待写剧本 → 待出图 → 待审核首帧 → 待生成视频 → 待配音 → 待合成 → 已完成
                ↑ 驳回 ↓
```

MVP 已实现（数据层 + API）：
- 设定圣经管理（世界观/角色卡/画风卡/负面词库/集数摘要）
- 分镜表生成（文本 → 分句 → 镜头，含景别/运动推断）
- 提示词编译器（自动注入角色外貌+画风+负面词，输出 MJ/SD/即梦/可灵格式）
- 素材版本管理（多版本存储，规范命名）
- 人工审核点（角色定稿/分镜确认/首帧/视频/成片 5 种审核类型）

待接入：外部生成工具（出图/视频/配音）、质检自动重试、剪映导出

---

## 独立部署（不使用 Docker）

### 后端

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env               # 按需修改 DATABASE_URL / AI_API_KEY

# 初始化数据库（首次部署）
alembic upgrade head

# 启动 API 服务
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 前端

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev                        # 开发模式 http://localhost:3000
# 或
npm run build && npm start         # 生产模式
```

## 验证脚本

```bash
cd backend
python ../scripts/smoke_import.py    # PM 核心模块导入测试
python ../scripts/smoke_import2.py   # AI/agent/api 模块导入测试
python ../scripts/check_deps.py      # 静态检查缺失的 app.* 依赖
python -m pytest tests               # 全量测试（136 个）
```

## 说明

- **开源协议**：GPL v3
- **验证状态**：pytest **237 通过**
- **数据库**：PostgreSQL（必须），Redis（可选，未配置时自动降级）
- **AI 模型**：支持 OpenAI / Anthropic / Gemini，通过环境变量切换
- **多模态**：支持 none / cloud / local 三后端可插拔配置
- **前端**：Next.js 16 + React 19 + Tailwind CSS + shadcn/ui
- **部署**：Docker Compose 一键启动（前端 + 后端 + PostgreSQL + Redis）
- **向后兼容**：现有 PM Agent API（`/api/pm/*`）完全保留，新增 `/api/v1/*` 并行
