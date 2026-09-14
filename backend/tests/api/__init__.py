"""API 集成测试包（T7）。

直接使用 app.main 模块级 app（真实路由 + 中间件），httpx ASGITransport 打请求，
通过 app.dependency_overrides 注入 sqlite 内存 session 与固定测试用户，避开真实 Postgres/Redis/JWT。
"""