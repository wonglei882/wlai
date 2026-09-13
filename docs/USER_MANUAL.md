# WLai 用户手册

> AI 内容一致性守护平台 + AI 漫剧制片（产品化版）
> 适用版本：2.0.0

---

## 目录

1. [产品简介](#1-产品简介)
2. [快速开始](#2-快速开始)
3. [首次登录与安全设置](#3-首次登录与安全设置)
4. [功能使用指南](#4-功能使用指南)
5. [Token 用量统计](#5-token-用量统计)
6. [监控与告警](#6-监控与告警)
7. [数据备份与恢复](#7-数据备份与恢复)
8. [常见问题 FAQ](#8-常见问题-faq)

---

## 1. 产品简介

WLai 提供两大产品线：

- **ConsistencyAgent** — 通用内容一致性守护（长篇小说 + 漫剧）。每 30 分钟自动巡检，检测并修复 AI 生成内容中的一致性问题（角色跳变、伏笔老化、世界观漂移、大纲漂移等），形成「巡检 → 诊断 → 决策 → 修复 → 验证」闭环。
- **ComicProductionAgent** — AI 漫剧制片流水线。设定圣经 → 分镜生成 → 提示词编译 → 素材管理 → 人工审核 → 合成，以「镜头」为最小单位，7 状态流转。

核心原则：**让 AI 不敢乱来**（外置记忆 + 提示词编译 + 人工审核 + 反馈闭环）。

---

## 2. 快速开始

### 2.1 系统要求

- Docker 20+ 和 Docker Compose v2+
- 4GB+ 内存
- AI 提供商 API Key（OpenAI / Anthropic / Gemini，可选，Mock 生成器可离线演示）

### 2.2 Docker 一键启动

```bash
# 1. 克隆项目
git clone <repo-url> && cd WLai

# 2. 运行启动脚本（首次会自动生成 .env 与随机密钥）
#    Windows:
.\start.ps1
#    Linux / Mac:
bash start.sh

# 3. 按提示编辑 .env 填入 AI API Key，再次运行启动脚本
```

启动后访问：

| 服务 | 地址 |
| --- | --- |
| 前端界面 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |
| 指标接口 | http://localhost:8000/metrics |

> 首次启动自动执行数据库迁移（`alembic upgrade head`），无需手动初始化。

### 2.3 独立部署（不使用 Docker）

见 [README.md](README.md)「独立部署」章节：后端 `pip install -r requirements.txt` + `alembic upgrade head` + `uvicorn`；前端 `npm install && npm run build && npm start`。

---

## 3. 首次登录与安全设置

1. 打开前端首页，使用 `.env` 中配置的 `LOCAL_AUTH_USERNAME` / `LOCAL_AUTH_PASSWORD` 登录。
2. **若使用默认弱密码**（如 `admin123`），系统会强制要求修改密码后才能继续使用。
3. 生产环境请务必：
   - 修改 `LOCAL_AUTH_PASSWORD` 为强密码；
   - 在 `.env` 中配置高强度随机 `SESSION_SECRET_KEY`（生产未配置将拒绝启动）。
     生成方式：`python -c "import secrets; print(secrets.token_urlsafe(48))"`。

---

## 4. 功能使用指南

### 4.1 小说工作台

- 创建小说项目，编写章节。
- 章节创建/更新后，PM Agent 自动执行因果推理、伏笔链扫描与一致性检查。
- 巡检发现的问题会进入「PM Agent → 诊断面板」，支持反馈与一键解决。

### 4.2 漫剧工作台

制片流水线（镜头 7 状态）：

```
待写剧本 → 待出图 → 待审核首帧 → 待生成视频 → 待配音 → 待合成 → 已完成
                ↑ 驳回 ↓
```

1. **设定圣经**：管理世界观、角色卡、画风卡、负面词库、集数摘要。
2. **分镜生成**：文本 → 分句 → 镜头（含景别/运动推断），生成后需人工确认。
3. **提示词编译**：自动注入角色外貌 + 画风 + 负面词，输出 Midjourney / SD / 即梦 / 可灵格式。
4. **镜头泳道看板**：以看板视图总览全部镜头状态，一键流转（进入出图 → 提交审核 → 审核通过 → …）。
5. **素材生成**：`生成素材` 调用生成器抽象层（默认 Mock 生成器，可离线演示；产物存放 `/generated` 静态目录）。
6. **人工审核点**：角色定稿 / 分镜确认 / 首帧 / 视频 / 成片 5 种审核类型，驳回自动回到对应状态。

### 4.3 PM Agent 总控台

- **运行状态**：启动 / 恢复 / 暂停 / 停止自主巡检引擎。
- **项目健康网格**：每个项目的健康状态概览。
- **巡检统计**：巡检轮次、覆盖项目、发现问题数、修复成功率等（进程重启后从快照恢复）。
- **诊断面板**：查看诊断日志、修复报告，提交反馈与解决。
- **自主度配置**：按项目设置自主度级别、置信度阈值、自动执行类型。

---

## 5. Token 用量统计

入口：侧边栏「用量统计」`/token-usage`。

- 汇总卡片：总消耗 / Prompt / Completion / 成本（USD）。
- 消耗趋势：按天折线图（7 / 14 / 30 天可切换）。
- 按功能分布：柱状图展示各功能模块 Token 占比。
- 按操作分布：明细排行与占比条。

数据来自 `GET /api/pm-token-usage/summary` 与 `/trend`。

---

## 6. 监控与告警

### 6.1 Prometheus 指标（/metrics）

`GET /metrics` 输出 Prometheus 文本格式指标，包含：

- **HTTP**：`wlai_http_requests_total`、`wlai_http_request_duration_seconds`
- **PM 质量闭环**：巡检轮次、问题数、修复/验证成功率、LLM token 消耗
- **系统资源**：进程内存、CPU、句柄数、线程数

示例 Prometheus 抓取配置：

```yaml
scrape_configs:
  - job_name: wlai
    metrics_path: /metrics
    static_configs:
      - targets: ["localhost:8000"]
```

### 6.2 Webhook 告警

通过 `POST /api/v1/webhooks` 注册回调（需 HMAC 签名密钥，≥8 字符）。支持事件：

| 事件 | 触发时机 |
| --- | --- |
| `issue_detected` | 巡检发现问题 |
| `scan_finished` | 巡检完成 |
| `fix_completed` | 修复完成 |
| `cost_threshold_exceeded` | 当日 Token 用量达到预算告警水位（每用户每日至多一次） |

回调请求带 `X-CA-Event`、`X-CA-Signature`（HMAC-SHA256）、`X-CA-Timestamp` 头，外部系统可用注册时提供的 secret 验签。

注册示例：

```bash
curl -X POST http://localhost:8000/api/v1/webhooks \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "<project_id>",
    "url": "https://your-server/webhook",
    "events": ["issue_detected", "cost_threshold_exceeded"],
    "secret": "your-signing-secret"
  }'
```

---

## 7. 数据备份与恢复

### 备份（Docker 环境）

```bash
# Linux / Mac
bash scripts/backup_pg.sh                 # 默认保留 14 天，输出到 ./backups
bash scripts/backup_pg.sh --keep 30 --output /mnt/backup

# Windows PowerShell
.\scripts\backup_pg.ps1
.\scripts\backup_pg.ps1 -Keep 30 -OutputDir D:\backups
```

建议配置 crontab / 计划任务每日执行。

### 恢复

```bash
docker compose exec -T db pg_restore -U wlai -d wlai --clean --if-exists \
  backups/wlai_YYYYMMDD_HHMMSS.dump
```

---

## 8. 常见问题 FAQ

**Q1: 启动脚本提示「未检测到 Docker」？**
安装 Docker Desktop（Windows）并确保已启动，`docker compose version` 可用。

**Q2: 首次启动后无法登录？**
确认 `.env` 中 `LOCAL_AUTH_USERNAME` / `LOCAL_AUTH_PASSWORD` 已配置；若使用默认弱密码，登录后会被强制修改密码。

**Q3: 生产启动时报错「生产环境必须配置 SESSION_SECRET_KEY」？**
在 `.env` 中配置高强度随机密钥后重启，参见 [第 3 节](#3-首次登录与安全设置)。

**Q4: 漫剧镜头「生成素材」无真实图？**
默认使用 Mock 生成器（离线演示）。接入真实生成平台需在生成器工厂层注册对应实现（`backend/app/services/generators/`）。

**Q5: 数据存在哪里？怎么找回？**
数据在 Docker 卷 `wlai_pgdata`（PostgreSQL）与 `wlai_redisdata`（Redis）中。定期执行 [第 7 节](#7-数据备份与恢复) 的备份脚本。

**Q6: 如何查看后端日志？**
`docker compose logs -f app`（后端）、`docker compose logs -f frontend`（前端）。

**Q7: 忘记管理员密码？**
在 `.env` 中修改 `LOCAL_AUTH_PASSWORD` 后重启服务即可（重新创建逻辑仅在该账户不存在时生效；若需强制重置，删除数据库中该用户记录后重启）。

---

## 附：安全清单

- [ ] 修改默认管理员弱密码
- [ ] 配置高强度 `SESSION_SECRET_KEY`
- [ ] 生产环境仅在内网暴露 `/metrics`（或增加认证）
- [ ] 开启数据库定时备份
- [ ] 妥善保管 Webhook 签名密钥
