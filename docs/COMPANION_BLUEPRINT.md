# 智能创作陪伴蓝图 —「苏格拉底 · 家教 · 百科全书 · 秘书」

> 版本：1.0.1 ｜ 2026-08-24 ｜ 落地范围：WLAI-PM（PM Agent 后端模块）
> **状态：✅ 已执行完成并通过自验收** ｜ 验证：demo 四维输出正常、smoke 回归 48/48、lint 0 错误、验收专项 25 项全过
> 交付：companion 包（6 模块）+ 种子百科（6 条目）+ 陪伴 API + 演示脚本 + 决策链路引导拦截

### 自验收修复记录（v1.0.1）
1. **白名单归一化**：真实巡检 issue_type 带 `pm_agent_` 前缀（`pm_agent_foreshadow_stale` 等），查表前自动归一化；补齐 `world_drift`（映射 `world_rule_drift` 链）、`outline_drift`、`paragraph_too_long`、`character_jump` 链。
2. **严重度排除修正**：severity 枚举为 critical/warning/info，`_NON_GUIDE_SEVERITIES` 修正为 `{'critical'}`（原含不存在的 `'high'`）。
3. **秘书语气映射修复**：`preferred_detail_level`（high/medium/low）→ 语气（温暖亲切/轻松自然/正式克制），原实现恒回退 warm。
4. **小贴士轮换**：按小时轮换，不再恒取第一条。
5. **tutor 清理**：删除冗余带 emoji 的 `compose_milestone_message`（由 secretary 权威实现）；示例层补 `paragraph_too_long`/`outline_drift`/`character_jump`。
6. **兼容性确认**：guide 结果与 manual/skip 短路同形状（decision/fix_result 无 DB 约束，可写），decisions 消费点仅读 `fix_attempted`/`verified` 计数，拦截短路安全。

## 一、蓝图定位

把 PM Agent 从「被动巡检 + 自动修复」升级为**四维智能创作陪伴**：

| 维度 | 人格 | 系统能力 | 一句话 |
|---|---|---|---|
| **S** | 苏格拉底的大脑 | 引导式提问，不直接给答案 | 「这个问题你怎么看？」 |
| **T** | 优秀家教的耐心 | 因材施教、分层反馈、犯错再引导 | 「别急，我们一起看——」 |
| **E** | 百科全书的储备 | 写作技法知识库 + 技能库检索注入 | 「关于伏笔回收，有三种常用手法」 |
| **P** | 私人秘书的贴心 | 主动关怀、个性化简报、低打扰 | 「今天进度不错，记得休息哦」 |

四维缩写 **STEP**，落成一个 `companion`（陪伴中枢）服务包。

## 二、现状盘点（探索结论）

### 已具备（可复用资产）
| 能力 | 现状位置 |
|---|---|
| 完整决策闭环 | `pm_agent_decision.diagnose_and_fix`（诊断→决策→修复→验证） |
| 三级自主度 | advisor / advisor_plus / autonomous（`pm_decision_policy.classify_by_score`） |
| 主动机制已通电 | `proactive_reporter` / `proactive_suggestions`（`pm_agent._run_proactive_report`） |
| 技能知识库 | `inspiration_sub.skill_system` 三级检索（全局→私有→向量→关键词）+ 晋升 |
| 用户画像 | `PMUserProfile`（experience_level / preferred_detail_level / skills_mastered） |
| 偏好学习 | `pm_preference_learner`（贝叶斯置信度） |
| 自调参 | `self_tuning` / `self_tuning_strategy`（连续失败升级、参数回滚） |
| 错误闭环 | MistakeLog / PMDiagnosticLog / PMDecisionLog / GoalStabilityLog 四表 |
| LLM 统一入口 | `AIService.generate_text` + `pm_ai_client.get_pm_ai_client` |
| 功能开关 | `pm_features.yaml` 分级（core/optional/batch） |

### 明显缺口（蓝图补强点）
1. **苏格拉底式引导**：全库无 socratic/引导式实现——纯空白
2. **耐心分层反馈**：有 `experience_level` 字段但未驱动反馈措辞分级
3. **百科知识库**：技能库是"经验沉淀"，缺"主动知识供给"（种子知识 + 检索注入）
4. **贴心话术**：主动报告是格式化模板，缺个性化语气/问候/鼓励

## 三、架构设计

```
                    ┌─────────────────────────────────────┐
  用户交互          │         companion 陪伴中枢            │
 ┌──────────┐      │  ┌───────────┐  ┌──────────────────┐ │
 │ 创作请求   │──┐   │  │ socratic  │  │  tutor           │ │
 │ PM API    │  │   │  │ 苏格拉底   │  │ 家教（分层反馈）    │ │
 └──────────┘  │   │  └───────────┘  └──────────────────┘ │
               ├──▶ │  ┌───────────┐  ┌──────────────────┐ │
 ┌──────────┐  │   │  │encyclopedia│  │ secretary        │ │
 │ PM 巡检   │──┘   │  │ 百科全书   │  │ 秘书（主动贴心）    │ │
 └──────────┘      │  └───────────┘  └──────────────────┘ │
                   │  ┌──────────────────────────────────┐ │
                   │  │ prompts.py（提示词模板库）           │ │
                   │  └──────────────────────────────────┘ │
                   └──────────────┬──────────────────────┘
                                  │ 懒导入（零循环风险）
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
           pm_agent_decision  skill_system    proactive_reporter
           （引导拦截点）      （技能检索复用）   （简报数据源）
```

### 模块划分（新增 6 个代码文件 + 1 份种子知识）
```
backend/app/services/companion/
├── __init__.py        # CompanionService 门面 + 决策引导钩子
├── socratic.py        # 维度S：引导式提问链
├── tutor.py           # 维度T：分层反馈 + 鼓励
├── encyclopedia.py    # 维度E：百科检索 + 注入
├── secretary.py       # 维度P：主动贴心话术
└── prompts.py         # 提示词模板（补齐工坊缺口）

backend/data/knowledge_seed/*.md   # 写作百科种子条目
backend/app/api/companion.py       # 陪伴 API（/companion/*）
scripts/companion_demo.py          # 四维能力演示脚本
```

### 接线策略（最小侵入 + 功能开关）
- `pm_features.yaml` 新增 `optional.companion.enabled`（默认 **false**，开启才生效）
- 唯一侵入点：`pm_agent_decision.diagnose_and_fix` 阶段 1 之前插入
  「苏格拉底引导拦截」——命中时返回 `decision='guide'`（与现有 early_result 同形状），
  不触自动修复；未开启 / 未命中 → 原路径不变
- companion 内部全部「懒导入 + 异常吞掉」，任何失败不影响 PM 主链路

## 四、四维详细设计

### S. socratic.py — 苏格拉底的大脑
- `should_guide(issue_type, severity, experience_level, autonomy_level)`：
  引导命中 = 非 critical 严重度 + 用户 beginner/intermediate + 非 autonomous 自主度 + 问题类型在引导表
- `build_socratic_chain(issue, project_ctx)`：每类问题生成 **3 级提问链**（现象确认 → 原因探询 → 方案自省），
  模板见 `prompts.py`；引导问题写入诊断面板，用户可逐问作答
- `socratic_redirect_if_needed(db, issue, project_id, user_id, diag_type, severity)`：
  供 `diagnose_and_fix` 调用的拦截入口，返回 `dict | None`

### T. tutor.py — 优秀家教的耐心
- `detect_experience_level(profile)`：读 `PMUserProfile.experience_level`，兜底按行为统计推断
- `format_tutored_feedback(issue, level, attempt_count, detail_pref)`：三层递进——
  - 首次犯错 → **原则**（讲清楚为什么）
  - 再次犯错 → **线索**（给方向不给答案）
  - 三次以上 → **示例**（给最小可仿写样例）
  - 输出含：`{tone, principle, steps[], example, encouragement}`
- `compose_encouragement(metric)`：修复成功 / 章节完成时的鼓励（结合里程碑）

### E. encyclopedia.py — 百科全书的储备
- 种子百科 `data/knowledge_seed/*.md`（对话/节奏/人物弧光/伏笔/场景/章末钩子）
- `search_knowledge(topic, top_k)`：关键词打分 + 复用 `skill_system.find_matching_skill` 检索用户技能库
- `get_knowledge_context(user_id, project_id, topic, db)`：返回可注入 system_prompt 的知识片段
  （参考 `_get_quick_diagnostic_summary` 的注入模式）
- `inject_knowledge(system_prompt, topic)`：把知识片段拼入提示词（未命中返回原样）

### P. secretary.py — 私人秘书的贴心
- `personal_greeting(hour)`：按时段问候（早/午/晚/夜）
- `compose_daily_briefing(project_ctx, report, profile)`：定制化每日简报
  （问候 + 进展 + 提醒 + 1 条创作小贴士 + 节流话术）
- `compose_milestone_message(ctx, milestone)`：每 10 章/首百章里程碑祝贺
- `compose_gentle_reminder(issue, profile)`：对未解决问题的低打扰提醒（按用户语气偏好调整）

### prompts.py — 提示词模板库（补齐工坊缺口）
分场景模板：`socratic_chain` / `tutor_feedback` / `knowledge_inject` / `secretary_brief`，
`render(name, **kw)` 统一渲染；为后续「提示词工坊」服务化预留位置。

## 五、可行性验证清单（执行前逐项确认）
1. `companion` 包全部模块可独立 import（零新依赖，只用现有库）
2. 懒导入不引入循环（companion 不顶层 import 任何 pm_* 核心模块；核心模块仅在函数内 import companion）
3. `pm_agent_decision` 侵入点改动后，两个 smoke 脚本仍 100% 通过
4. `socratic_redirect_if_needed` 在功能开关默认关闭时返回 None（原行为不变）
5. 四维函数可用纯规则 + 可选 LLM 跑通（demo 脚本演示输出）

## 六、执行计划
| 步骤 | 内容 |
|---|---|
| 1 | 新建 `companion/prompts.py` + `socratic.py` + `tutor.py` |
| 2 | 新建 `encyclopedia.py` + 种子知识条目 |
| 3 | 新建 `secretary.py` + `__init__.py` 门面 |
| 4 | `pm_features.yaml` 加 companion 开关；`pm_agent_decision.py` 插引导拦截点 |
| 5 | 新建 `api/companion.py` + `scripts/companion_demo.py` |
| 6 | 验证（import + smoke + demo 输出）+ 提交 git |
