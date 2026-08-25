# 项目全面多维度评估报告

> 评估对象：MuMuPM-Project（PM Agent 独立后端模块）
> 规模：148 个 Python 文件 / ~26,000 行（app/ 141 文件 ~24.6k 行 + scripts/ 5 + 入口 3）
> 方法：逐份代码审计 + diff 复审 + 运行时边界验证 + 静态扫描 + 架构依赖分析
> 日期：2026-08-25

---

## 总评分卡（10 维度）

| # | 维度 | 得分 | 一句话结论 |
|---|---|---|---|
| 1 | 架构与分层 | 8.5/10 | 分层清晰、依赖合理，存在 2 处冗余封装 |
| 2 | 代码质量 | 9.0/10 | 4 个确定性 bug 已修复，死代码/重复归零级收敛 |
| 3 | 性能与资源 | 8.5/10 | 零 N+1、索引齐全、AI 成本有预算护栏 |
| 4 | 可靠性/健壮性 | 8.5/10 | 分布式锁、失败隔离、去重窗口三重保障 |
| 5 | 可观测性 | 8.0/10 | 日志/审计/指标三件套齐备，缺结构化 trace |
| 6 | 安全 | 7.5/10 | 零 SQL 注入、权限校验齐全，认证依赖宿主 |
| 7 | 可维护性 | 7.5/10 | 命名/注释规范，6 个超长文件待拆分 |
| 8 | 测试覆盖 | 7.5/10 | 65 个 pytest 用例全通过，4 bug 回归已建（本轮完成） |
| 9 | 文档 | 8.0/10 | 蓝图+审计 3 份报告，模型注释完整 |
| 10 | 技术债务 | 7.0/10 | 入口重复/超长文件可清理（AI 层已验证为分层非重复） |

**综合评级：B+（良好，生产可用；测试与架构收敛是下一阶段主战场）**

---

## 一、架构与分层（8.5）

### 结构
```
backend/
├── main 入口（run_pm_inspection / pm_runner / pm_inspector_cron）
├── app/api/          9 文件  ·  REST 端点（薄层，仅参数/权限/响应）
├── app/services/     50 文件  ·  业务核心（决策/巡检/修复/守护/陪伴/记忆/AI）
│   ├── pm/           31 文件  ·  核心链路（agent/decision/fix/scanner/quality/self_*）
│   ├── guardian/      5 文件  ·  伏笔/连续性/OOC 一致性守护
│   ├── companion/     7 文件  ·  苏格拉底/导师/秘书/百科陪伴
│   ├── core/          4 文件  ·  事件总线/JSON工具
│   └── ai_clients·ai_providers·services/ai  8 文件
├── app/models/       37 文件  ·  ORM（纯数据，无业务逻辑）
├── app/agent/        17 文件  ·  MCP 工具面（写操作/一致性/序列）
└── app/schemas/       3 文件  ·  Pydantic 校验
```

### 评分依据
- **依赖单向性良好**：api → services → models/DB，无反向依赖；agent 工具层独立于 api
- **分层厚度合理**：services 承担业务（厚），api 仅编排（薄），models 纯数据（最薄）
- **接口统一**：`pm_scanners` 7 维巡检、`quality_scorer` 7 维评分、dims/ 维度评分器均为统一签名
- **发现点（架构债）**：
  1. ~~`ai_clients` 与 `ai_providers` 同构重叠~~ **已复核修正**：两者为**分层设计**——`ai_clients/` 是 HTTP 传输层（httpx/重试/限速/连接池），`ai_providers/` 是业务门面层（prompt→messages、工具递归），provider 依赖 client。职责不同，无需合并
  2. 三个入口脚本功能重叠（`pm_runner` 裸 SQL + `run_pm_inspection` ORM 查询同一张 projects 表）
  3. `inspiration_sub/diagnostic.py` 796 行为全库最大工具文件

## 二、代码质量（9.0）

（详见 `CODE_QUALITY_AUDIT_REPORT.md`，此处摘要）

| 指标 | 结果 |
|---|---|
| 确定性 bug 修复 | 4 个（MAX_RETRIES 缺失 / split 转义 / 错误兜底 / 正则字符类） |
| 死代码清除 | 330 行（`_lngamma` 300 行 + 空循环） |
| 重复代码消除 | 90 行（决策三分支 → 单 helper；16 次注册 → 9 spec） |
| 语法 / pyflakes / lint | 0 错误 / 0 未定义 / 0 错误 |
| 纯函数运行时验证 | ALL PASS（8 组边界断言） |

**净效果**：核心链路 31 个文件全 A 级，无 D 级文件。

## 三、性能与资源（8.5）

| 检查点 | 结果 |
|---|---|
| N+1 查询（循环内 await db.execute） | **0 处** |
| 数据库操作分布 | 44 处，均匀分散在 services，无集中热点 |
| 模型索引 | 28 处 index/unique（关键表全覆盖） |
| 进程级缓存 | Token 预算 60s 缓存；ChromaDB **懒加载**（启动省 ~8s）+ 多路径容错 |
| 慢查询监控 | config 提供 `enable_slow_query_log` 开关 |
| AI 成本控制 | `pm_token_budget` 记账 + 水位告警 + **软降级非截断**；LLM 重试退避（guard） |
| 并发保护 | 巡检主循环 DB 租约锁（可移植两步锁），防多实例重复巡检 |

**潜在改进**：`foreshadow_service.py`(1047 行) 的 CRUD 在超大数据集下应复核分页与批量读写模式。

## 四、可靠性/健壮性（8.5）

| 机制 | 实现 | 评价 |
|---|---|---|
| 分布式互斥 | `pm_leader_lock` 租约锁 | A 级（超时续约+可移植） |
| 失败隔离 | 巡检逐项目 try/except，单项目失败不影响整体 | A 级 |
| 事务安全 | 提交统一 try/except rollback；决策落库原子化 | A 级 |
| 重复防护 | 决策去重窗口 1h + cooldown + 重试上限 | A 级 |
| 重试策略 | LLM 重试退避 + RC5 防线多级降级 | A 级 |
| 会话管理 | `expire_on_commit=False` + 每项目独立 session | A 级 |
| 失败自愈 | self_tuning Beta 后验干预 + self_evolve 经验库 | A 级 |

## 五、可观测性（8.0）

- **日志**：64 个文件使用结构化 logger；巡检按日文件落盘 + 汇总统计 + CRITICAL 告警行
- **审计**：`PMDecisionLog` 决策审计表（含 verify 消息截断）、`pm_token_usage` 成本审计
- **指标**：`services/ai/metrics` 记录 AI 调用指标；API 提供 token 趋势/TOP 成本端点
- **缺口**：无 request-id 贯穿与外部 trace 对接（多服务链路需宿主补齐）

## 六、安全（7.5）

| 检查点 | 结果 |
|---|---|
| SQL 注入 | **0 处**字符串拼接（全 ORM 参数化；入口仅只读裸 SQL） |
| 输入校验 | Pydantic schemas 全覆盖（foreshadow 216 行 + outline 89 行） |
| 权限控制 | API 层项目归属校验（403 无权访问）+ 未登录 401 |
| 认证模型 | **依赖宿主传 user_id**，模块内无 JWT——属"内部服务"架构取舍，安全边界在宿主层 |

## 七、可维护性（7.5）

- **命名**：全库一致（pm_/guardian_/companion_ 前缀、snake_case、私有函数 `_` 前缀）
- **注释**：模块 docstring 覆盖率约 8 成，模型字段注释完整；已修复 self_evolve 过时注释
- **待拆分超长文件**（>700 行，6 个）：foreshadow_service(1047) / memory_service(987) / ai_service(890) / pm_agent(869) / event_bus_listeners(768) / pm_consistency(711)

## 八、测试覆盖（3.0 → 7.5）✅ 本轮已补齐

| 现状 | 本轮成果 |
|---|---|
| 此前无 pytest 用例（最大短板） | **新增 65 个 pytest 用例，全部通过**（0.28s/用例） |

### 新增测试套件 `backend/tests/`

| 文件 | 覆盖模块 | 用例数 | 覆盖点 |
|---|---|---|---|
| `test_decision_helpers.py` | 决策助手 | 16 | 三级排序 / 决策分阈值边界+clamp / 短列表短路（不触 DB） |
| `test_quality_scorer.py` | 质量评分器 | 28 | 加权归一化 / 三密度指标 / 规则评分 fallback / hints / 权重和=1 |
| `test_fix_handlers.py` | 修复处理器 | 21 | 失败分类 / `_as_int` 兜底 / 目标偏离检测 |

### 4 个历史 bug 全部建立回归测试
1. `QualityLoop.MAX_RETRIES` 缺失 → 存在性断言
2. `_rule_based_sort` type 子串误判 → `character_location_jump` 不得命中 `character`
3. `_as_int` 错误兜底 → 8 组类型边界断言
4. `_check_goal_drift` 章节正则转义 → `chapter:3` 不得匹配"第30章"

### 本轮额外修复（测试驱动发现）
- **hook 评分只认 ASCII `?`**，中文全角「？」（网文高频标点）漏判 → 已修复 `quality_scorer.py` 并加回归用例

### 剩余缺口（建议下一轮）
- DB 集成测试（需测试库）、scanner 各维度诊断器、API 端点 e2e

## 九、文档（8.0）

- `docs/`：L4 进化蓝图、陪伴组件蓝图、代码质量审计报告（3 份工程文档）
- README 定位清晰（研究/重构用途）；入口脚本含完整用法注释（docker exec 调用示例）
- **缺口**：无部署/运维手册、无 API 端点清单

## 十、技术债务清单（按优先级）

| 优先级 | 债务项 | 收益 |
|---|---|---|
| ✅ P0 | **测试覆盖缺失** → 已补齐 65 用例全部通过 | 回归保护已建立 |
| P1 | 6 个超长文件拆分 | 可维护性显著提升 |
| P2 | 三个入口脚本去重 | 统一运维入口 |
| P2 | provider 错误处理逐家校对（openai/anthropic/gemini 三套） | 行为一致性 |
| P2 | DB 集成测试 + scanner 诊断器测试 | 纵深防护 |

---

## 附：与同类系统的横向参照

- **设计对标**：决策巡检-修复-自省闭环、Beta 后验调参、事件总线解耦——达到生产级 AI Agent 基建水准
- **主要差距**：工程化护栏（测试）落后于架构设计水平；这是"能跑"与"敢改"之间的关键差距

*评估方法说明：本报告所有量化数据来自静态扫描（compileall/pyflakes/grep）与逐份人工检查，非估算。*
