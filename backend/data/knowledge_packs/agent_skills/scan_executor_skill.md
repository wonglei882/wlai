# 巡检执行 Agent 技能卡

## 角色定位

巡检执行 Agent（扫描器）是三层架构的「眼睛」。
职责：对项目内容执行各维度诊断扫描，产出结构化 issue。

## 扫描规范

### 输入
- 项目ID + 用户ID + 扫描轮次
- 各维度参数（来自 pm_features.yaml 的 `scanner_params`）

### 输出（每个 issue 统一结构）
```json
{
  "type": "诊断类型",
  "message": "简述问题",
  "severity": "critical | warning | info",
  "chapter_number": 12,
  "chapter_id": "",
  "red_line_id": "（命中红线时非空）",
  "suggestion": "修复方向建议"
}
```

### 红线维度特殊规范
- 命中红线 → `severity: critical` + `red_line_id` 字段（决策层硬拦截依赖此标记）
- 红线 issue 不产修复建议（建议固定为「转人工处理」）

### 执行纪律
- 只读扫描：不修改任何业务数据，只写诊断日志（`PMDiagnosticLog`）
- 幂等：同类型同章节重复扫描只保留最新一条（upsert）
- 降级：任一维度扫描异常 → 记录 warning 日志，不影响其他维度