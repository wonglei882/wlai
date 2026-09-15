# VisGuard OpenAI 兼容接口

> 位置：`POST /api/v1/visguard/openai/*`（内嵌于 WLai 平台，复用 JWT 认证）

## 兼容性声明

本接口**不完全兼容** OpenAI API。兼容的子集如下。

### ✅ 已实现：POST /api/v1/visguard/openai/images/generations

- 请求格式与 OpenAI `POST /v1/images/generations` 一致（prompt / model / n / size / response_format / style / user）
- 响应格式与 OpenAI `ImagesResponse` 一致（`created` + `data[].b64_json`）
- **差异**：
  - **必须**附加 VisGuard 扩展字段 `project_id`（项目归属校验，403 越权拒绝）
  - `model` 参数被忽略，使用 VisGuard 配置中的模型
  - 仅支持 `response_format="b64_json"`，不支持 `url`（传其他值 422）
  - 仅支持 `n=1`（`n>1` 由 pydantic 约束 422）
  - 尺寸仅支持 `256x256 / 512x512 / 1024x1024 / 1024x1792 / 1792x1024 / 2048x2048`
  - 扩展字段 `character_id`（角色一致性参考）、`control_type + control_image_b64` 在生图后端（Phase C）接入后生效；当前返回明确的 not_implemented 错误

### ❌ 501 Not Implemented

- `POST /api/v1/visguard/openai/chat/completions` → 501（含 stream=true）
- `POST /api/v1/visguard/openai/embeddings` → 501
- `GET  /api/v1/visguard/openai/models` → 501

## 认证

使用平台一致的 `Authorization: Bearer <wlai_token>`（JWT，与 `/api/pm/*` 等相同）。
API Key 体系（`VG_API_KEYS`）不在内嵌架构内支持——如需独立 Key 化，请走独立部署形态。

## 错误格式

错误响应体为 OpenAI 风格：

```json
{
  "error": {
    "message": "生图功能未启用（VisGuard 未配置云端模式）",
    "type": "invalid_request_error",
    "code": "generate_not_available"
  }
}
```

对应 HTTP 状态码：422（参数校验）/ 501（未实现 / 未启用）/ 500（执行失败）。