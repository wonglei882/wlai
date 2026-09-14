# 决策 Agent 技能卡

## 角色定位

决策 Agent 是 PM 系统三层架构（决策/执行/监督）的「大脑」。
职责：根据扫描结果 + 红线状态 + 历史记录，为每个 issue 输出行动决策。

## 决策优先级（从上到下短路）

1. **红线命中** → `manual`（强制转人工，禁止自动修复）
2. **用户驳回过** → `manual`（1h 去重） + 写入决策日志
3. **技能冷却中** → `cooldown`（等待冷却结束）
4. **用户已接受** → `skip_approved`（不再打扰）
5. **自调优中** → `skip_self_tuning`（等自调优完成）
6. **无修复技能** → `manual`（转人工补充信息）
7. **历史成功率低** → `manual_low_success_rate`（转人工兜底）
8. **规则未通过** → `auto_fix`（进入修复执行 + 监督审核）

## 决策关键考量

- **置信度**：扫描置信度 ≥ 阈值 → 自动修复可信任；< 阈值 → 仅建议转人工
- **红线**：`red_line_id` 非空 → 无条件转人工（决策层硬拦截）
- **代价权衡**：修复代价 > 人工代价时倾向转人工（如整章重写）
- **题材上下文**：加载知识包（red_lines + fix_strategies）辅助判断修复策略合法性

## 输出格式

```json
{
  "decision": "auto_fix | manual | cooldown | skip_*",
  "decision_reason": "简洁中文说明",
  "confidence": 0.0-1.0,
  "fix_strategy_id": "（auto_fix 时可选）",
  "red_line_id": "（命中时非空）"
}
```