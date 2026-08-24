# L4 升级方案 ——「经验进化」（Experience Evolution）

> 版本：1.0.0 ｜ 2026-08-25 ｜ 目标：从 **L3 自持运行** 跨入 **L4 创新进化** 门槛
> 核心转变：从「每次重新修复、每次按画像读取输出」→「**从经验中归纳方法、反哺个性、自我修正**」
> **状态：✅ 已实施完成并通过验收** ｜ 验证：L4 专项 27/27、smoke 48/48、lint 0、demo 回归正常
> 提交边界：工作副本不含 Alembic（宿主管理建表）；新表经 `models/__init__.py` 注册进 `Base.metadata`（33 张表）

## 现状（L3）与差距（L4）

| 能力 | L3 现状 | L4 需要 | 本次升级 |
|---|---|---|---|
| 修复 | 每次重新生成，成功经验即弃 | **沉淀已验证方案并复用** | 闭环 1：修复模式库 |
| 个性 | 画像只读（零写入点） | **从决策结果反哺画像** | 闭环 2：画像学习 |
| 引导 | 一次性提问，效果无反馈 | **记录采纳/解决信号，可调参** | 闭环 3：引导反馈 |

## 三大闭环

### 闭环 1：修复模式库（Fix Playbook）—— 方法论沉淀
- 新表 `pm_fix_patterns`：`issue_type` / `pattern_text`(验证通过的方案) / `source_decision_id` / `success_count` / `use_count` / `last_used_at`
- **沉淀**：`_finalize_decision` 中 `fix_result=='success'` 且 `fix_action` 有效 → 同类型已有则 `success_count+1`，否则新建（`learn_fix_pattern`）
- **复用**：`_decide_action` 评分前查同类型 pattern（`success_count>=1`）→ 命中注入 `_pattern_boost=min(0.10, success_count*0.03)` 到决策评分，并 `use_count+1`
- 效果：成功经验让系统「更敢修、更优先修」→ 修复稳定性随使用增长，逼近「方法论生成」

### 闭环 2：画像学习（User Learning）—— 个性适配进化
- 新服务 `pm_user_learning.learn_from_decision(db, user_id, diag_type, fix_result, verified)`
- **技能积累**：修复成功 → 该类型对应技能写入 `skills_mastered`（上限 20，防膨胀）
- **水平重估**：成功 → `question_type_counts['intermediate']+1`；失败 → `['beginner']+1`；每 `recompute_every=20` 次按加权占比重算 `experience_level`（最小样本 5，防抖动）
- 调用点：`_finalize_decision` 指标采集后（非阻塞，独立 commit）

### 闭环 3：引导采纳反馈（Guidance Feedback）—— 引导效果可学习
- 新表 `pm_guidance_feedback`：`decision_log_id` / `project_id` / `user_id` / `issue_type` / `adopted` / `solved`
- 服务 `companion.guidance_feedback.record_guidance_feedback`
- API：`POST /api/companion/guidance/feedback`
- 本期落地**信号链路**（为 V2 引导链加权调参供数据）

## 控制与安全
- 总开关 `optional.learning`（默认 **false**，与 companion 独立）
- 所有学习逻辑 try/except 包裹 + 独立 commit：**任何失败仅日志，不破坏主决策链路**
- 新表由 `models/__init__.py` 注册 + `create_all` 自动建表（无需迁移脚本）
- 复用只做评分提升与计数，**不做文本注入**（handler 行为不可控，留作 V2）

## 实施清单
1. 模型：`pm_fix_pattern.py` / `pm_guidance_feedback.py` + `models/__init__.py` 注册
2. 服务：`pm_fix_pattern.py`（沉淀/查询/计数）/ `pm_user_learning.py` / `companion/guidance_feedback.py`
3. 接线：`_finalize_decision` 沉淀+学习；`_decide_action` 复用
4. API：`companion` 增加 feedback 端点
5. 配置：`pm_features.yaml` 增 `optional.learning`

## 验证
- 专项脚本：沉淀/复用/boost、画像升级路径（含防抖动）、反馈落库、开关关闭零副作用
- smoke 回归 48/48 + lint 0
