"""VisGuard OpenAI 兼容端点测试（P0-5）— api_env 集成基座。

覆盖（schema/映射等纯逻辑见 tests/test_openai_compat.py）:
- 501 未实现端点（chat/embeddings/models）
- images/generations：参数校验 / generate 未启用 / 越权拒绝
"""

import pytest


class TestOpenAIEndpoints:
    @pytest.mark.asyncio
    async def test_chat_completions_501(self, api_client):
        r = await api_client.post('/api/v1/visguard/openai/chat/completions', json={})
        assert r.status_code == 501
        body = r.json()
        assert 'error' in body
        assert body['error']['code'] == 'not_implemented'

    @pytest.mark.asyncio
    async def test_embeddings_501(self, api_client):
        r = await api_client.post('/api/v1/visguard/openai/embeddings', json={})
        assert r.status_code == 501

    @pytest.mark.asyncio
    async def test_models_501(self, api_client):
        r = await api_client.get('/api/v1/visguard/openai/models')
        assert r.status_code == 501

    @pytest.mark.asyncio
    async def test_images_validation_error(self, api_client):
        # n>1 → pydantic 422（函数体未进入，无需 project）
        r = await api_client.post(
            '/api/v1/visguard/openai/images/generations',
            json={'project_id': 'p1', 'prompt': 'x', 'n': 2},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_images_generate_not_configured(self, api_client, seed_project, monkeypatch):
        # generate_backend=none → 501 generate_not_available
        from app.config import settings
        monkeypatch.setattr(settings, 'visguard_generate_backend', 'none')
        project_id = await seed_project()
        r = await api_client.post(
            '/api/v1/visguard/openai/images/generations',
            json={'project_id': project_id, 'prompt': 'x'},
        )
        assert r.status_code == 501
        body = r.json()
        assert body['error']['code'] == 'generate_not_available'

    @pytest.mark.asyncio
    async def test_images_foreign_project_forbidden(self, api_client, seed_project):
        # 越权 project → 403/404（_owned_project）
        await seed_project(user_id='u_other_owner')
        r = await api_client.post(
            '/api/v1/visguard/openai/images/generations',
            json={'project_id': 'p-foreign', 'prompt': 'x'},
        )
        assert r.status_code in (403, 404)