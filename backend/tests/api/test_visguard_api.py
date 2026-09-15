"""VisGuard API 集成测试（能力矩阵架构）。

覆盖（T7 风格：真实 ASGI app + sqlite 内存库 + FakeClipEncoder 注入单例）：
- /status：启用/禁用两态（禁用不触发模型下载）
- /capabilities：能力发现字段契约
- 角色 CRUD：注册/列表/删除/追加图/相似度（假 CLIP + 临时索引目录）
- 安全：越权 403 / 图片超限 400 / 非法图片 400
- 异步任务：generate=none → 503；generate=cloud → 202 + 查询 + 取消 + SSE
"""

import io

import numpy as np
import pytest_asyncio
from PIL import Image

from app.config import settings

TEST_USER_ID = 'u_test_api_user'
OTHER_USER_ID = 'u_test_api_other'


class FakeClipEncoder:
    """CLIP 测试替身：基于 4x4 RGB 色块生成确定性 48 维归一化向量（无需真实模型）。

    相同图片 → 相同向量；不同颜色 → 不同向量（可验证相似度排序与过滤）。
    """

    is_loaded = True
    is_available = True
    load_error = None
    embedding_dimension = 48

    def encode_images(self, images) -> np.ndarray:
        vecs = []
        for img in images:
            arr = np.asarray(
                img.convert('RGB').resize((4, 4)), dtype=np.float32,
            ).flatten() / 255.0
            norm = np.linalg.norm(arr) + 1e-9
            vecs.append(arr / norm)
        return np.stack(vecs).astype(np.float32)

    def encode_image(self, image) -> np.ndarray:
        return self.encode_images([image])[0]

    def unload(self):
        pass


def _png_bytes(rgb: tuple[int, int, int], size: int = 64) -> bytes:
    """生成纯色 PNG 字节（multipart 上传用）。"""
    buf = io.BytesIO()
    Image.new('RGB', (size, size), rgb).save(buf, format='PNG')
    return buf.getvalue()


@pytest_asyncio.fixture
async def vg_service(api_client, tmp_path, monkeypatch):
    """注入 VisGuard 单例：假 CLIP + 临时索引/缓存目录（不污染真实 DATA_DIR）。

    通过模块级单例变量直接注入（get_visguard_service 的 _instance），
    测试结束重置，避免影响其他测试模块。
    """
    import app.services.visguard as vg_mod

    monkeypatch.setattr(settings, 'visguard_cache_dir', str(tmp_path / 'cache'))
    svc = vg_mod.VisGuardService(index_root=str(tmp_path / 'index'))
    svc.clip = FakeClipEncoder()
    vg_mod._instance = svc
    vg_mod._initialized = True
    yield svc
    vg_mod._instance = None
    vg_mod._initialized = False


async def _register(client, pid: str, name: str = '主角', rgb=(240, 40, 40)) -> str:
    """注册角色并返回 character_id。"""
    files = {'image': ('t.png', _png_bytes(rgb), 'image/png')}
    resp = await client.post(
        '/api/v1/visguard/characters',
        files=files,
        data={'project_id': pid, 'name': name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()['character']['id']


# =============================================================================
# /status
# =============================================================================

async def test_status_disabled_without_service(api_client, monkeypatch):
    """服务未注入（能力矩阵全关）→ enabled=false，不抛错、不触发模型下载。"""
    import app.services.visguard as vg_mod

    for attr in ('visguard_embedding_backend', 'visguard_preprocess_backend',
                 'visguard_generate_backend', 'visguard_inspect_backend'):
        monkeypatch.setattr(settings, attr, 'none')
    vg_mod._instance = None
    vg_mod._initialized = False
    resp = await api_client.get('/api/v1/visguard/status')
    assert resp.status_code == 200
    data = resp.json()
    assert data['enabled'] is False
    assert 'reason' in data


async def test_status_enabled(api_client, vg_service):
    resp = await api_client.get('/api/v1/visguard/status')
    assert resp.status_code == 200
    data = resp.json()
    assert data['enabled'] is True
    caps = data['capabilities']
    assert caps['embedding']['available'] is True
    assert caps['embedding']['backend'] == 'local'
    assert caps['generate']['available'] is False  # 默认 generate_backend=none
    assert data['clip']['available'] is True  # 假 CLIP 已"加载"，不触发下载
    assert 'cache' in data  # 三级缓存统计


# =============================================================================
# /capabilities 能力发现
# =============================================================================

async def test_capabilities_endpoint(api_client, vg_service):
    resp = await api_client.get('/api/v1/visguard/capabilities')
    assert resp.status_code == 200
    data = resp.json()
    assert data['enabled'] is True
    assert 'embedding' in data['capabilities']
    assert data['capabilities']['generate'] is False
    defaults = data['defaults']
    assert defaults['max_upload_mb'] == settings.visguard_max_upload_mb
    assert defaults['threshold'] == settings.visguard_default_threshold


# =============================================================================
# 角色 CRUD
# =============================================================================

async def test_register_character(api_client, vg_service, seed_project):
    pid = await seed_project()
    files = {'image': ('t.png', _png_bytes((240, 40, 40)), 'image/png')}
    resp = await api_client.post(
        '/api/v1/visguard/characters',
        files=files,
        data={'project_id': pid, 'name': '主角', 'description': '红衣'},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body['project_id'] == pid
    assert body['character']['name'] == '主角'
    assert body['character']['image_count'] == 1


async def test_register_foreign_project_forbidden(api_client, vg_service, seed_project):
    """其他用户的项目 → 403（归属校验在编码前，不浪费推理）。"""
    pid = await seed_project(user_id=OTHER_USER_ID)
    files = {'image': ('t.png', _png_bytes((240, 40, 40)), 'image/png')}
    resp = await api_client.post(
        '/api/v1/visguard/characters',
        files=files,
        data={'project_id': pid, 'name': '偷图'},
    )
    assert resp.status_code == 403


async def test_register_oversize_image_400(api_client, vg_service, seed_project):
    """超过 visguard_max_upload_mb → 400（解码前拦截，不占内存）。"""
    pid = await seed_project()
    oversize = b'x' * (settings.visguard_max_upload_mb * 1024 * 1024 + 1)
    files = {'image': ('big.png', oversize, 'image/png')}
    resp = await api_client.post(
        '/api/v1/visguard/characters',
        files=files,
        data={'project_id': pid, 'name': '大图'},
    )
    assert resp.status_code == 400
    assert '大小限制' in resp.json()['error']


async def test_register_invalid_image_400(api_client, vg_service, seed_project):
    pid = await seed_project()
    files = {'image': ('bad.png', b'not an image at all', 'image/png')}
    resp = await api_client.post(
        '/api/v1/visguard/characters',
        files=files,
        data={'project_id': pid, 'name': '坏图'},
    )
    assert resp.status_code == 400


async def test_list_characters(api_client, vg_service, seed_project):
    pid = await seed_project()
    await _register(client=api_client, pid=pid, name='主角')
    await _register(client=api_client, pid=pid, name='配角', rgb=(40, 40, 240))

    resp = await api_client.get('/api/v1/visguard/characters', params={'project_id': pid})
    assert resp.status_code == 200
    chars = resp.json()['characters']
    assert len(chars) == 2
    assert all(c['embedding_count'] == 1 for c in chars)


async def test_add_image_and_delete(api_client, vg_service, seed_project):
    pid = await seed_project()
    cid = await _register(client=api_client, pid=pid, name='主角')

    # 追加参考图 → embedding_count=2
    files = {'image': ('t2.png', _png_bytes((20, 200, 20), size=128), 'image/png')}
    resp = await api_client.post(
        f'/api/v1/visguard/characters/{cid}/images',
        files=files,
        data={'project_id': pid},
    )
    assert resp.status_code == 201
    assert resp.json()['image_id']

    lst = await api_client.get('/api/v1/visguard/characters', params={'project_id': pid})
    assert lst.json()['characters'][0]['embedding_count'] == 2

    # 删除 → 200；再删 → 404
    dr = await api_client.delete(
        f'/api/v1/visguard/characters/{cid}', params={'project_id': pid},
    )
    assert dr.status_code == 200
    dr2 = await api_client.delete(
        f'/api/v1/visguard/characters/{cid}', params={'project_id': pid},
    )
    assert dr2.status_code == 404


async def test_add_image_missing_character_404(api_client, vg_service, seed_project):
    pid = await seed_project()
    files = {'image': ('t.png', _png_bytes((240, 40, 40)), 'image/png')}
    resp = await api_client.post(
        '/api/v1/visguard/characters/no-such-id/images',
        files=files,
        data={'project_id': pid},
    )
    assert resp.status_code == 404


# =============================================================================
# /similarity
# =============================================================================

async def test_similarity_ranks_matching_character_first(api_client, vg_service, seed_project):
    pid = await seed_project()
    hero = await _register(client=api_client, pid=pid, name='主角', rgb=(240, 40, 40))
    await _register(client=api_client, pid=pid, name='路人', rgb=(40, 40, 240))

    files = {'image': ('q.png', _png_bytes((230, 50, 50)), 'image/png')}
    resp = await api_client.post(
        '/api/v1/visguard/similarity',
        files=files,
        data={'project_id': pid, 'top_k': '5'},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body['query_hash']
    results = body['results']
    assert results and results[0]['character_id'] == hero
    assert results[0]['score'] > 0.9
    assert all(
        results[i]['score'] >= results[i + 1]['score']
        for i in range(len(results) - 1)
    )


async def test_similarity_threshold_filters_low(api_client, vg_service, seed_project):
    pid = await seed_project()
    await _register(client=api_client, pid=pid, name='主角', rgb=(240, 40, 40))
    files = {'image': ('q.png', _png_bytes((10, 10, 10)), 'image/png')}
    resp = await api_client.post(
        '/api/v1/visguard/similarity',
        files=files,
        data={'project_id': pid, 'top_k': '5', 'threshold': '0.99'},
    )
    assert resp.status_code == 200
    assert resp.json()['results'] == []


# =============================================================================
# 异步任务 /jobs
# =============================================================================

async def test_jobs_rejected_when_generate_disabled(api_client, vg_service, seed_project):
    """默认 generate_backend=none → 503（不产生僵尸任务）。"""
    pid = await seed_project()
    resp = await api_client.post(
        '/api/v1/visguard/jobs', json={'project_id': pid, 'prompt': '测试'},
    )
    assert resp.status_code == 503
    assert '生成后端未配置' in resp.json()['error']


async def test_jobs_flow_create_query_cancel(api_client, vg_service, seed_project, monkeypatch):
    """generate=cloud → 202 创建 → 详情可查 → 取消。"""
    monkeypatch.setattr(settings, 'visguard_generate_backend', 'cloud')
    pid = await seed_project()

    resp = await api_client.post(
        '/api/v1/visguard/jobs',
        json={'project_id': pid, 'prompt': '一个红衣少女', 'provider': 'sansi'},
    )
    assert resp.status_code == 202
    body = resp.json()
    job_id = body['job_id']
    assert body['status'] == 'pending'
    assert 'events' in body['message']

    detail = await api_client.get(f'/api/v1/visguard/jobs/{job_id}')
    assert detail.status_code == 200
    d = detail.json()
    assert d['job_id'] == job_id
    assert d['status'] in ('pending', 'running', 'failed')
    assert 'created_at' in d

    cancel = await api_client.post(f'/api/v1/visguard/jobs/{job_id}/cancel')
    # 占位生成器秒失败 → 取消可能已被 409 拒绝；两态均为合法收敛路径
    assert cancel.status_code in (200, 409)


async def test_jobs_sse_emits_terminal_event(api_env, vg_service, seed_project, monkeypatch):
    """SSE 流在终态后自动关闭并推送终态事件。

    测试环境无真实 PostgreSQL 后台 worker（worker 依赖真实引擎会挂起），
    因此直接落库置终态（SSE 以 DB 状态为准），确定性验证流协议。
    """
    from app.models.task import AsyncTask

    client, Session = api_env
    monkeypatch.setattr(settings, 'visguard_generate_backend', 'cloud')
    pid = await seed_project()

    resp = await client.post('/api/v1/visguard/jobs', json={'project_id': pid, 'prompt': '测试'})
    job_id = resp.json()['job_id']

    async with Session() as s:
        t = await s.get(AsyncTask, job_id)
        t.status = 'completed'
        t.result = {'artifacts': [], 'duration_ms': 1, 'provider': 'sansi'}
        await s.commit()

    stream = await client.get(
        f'/api/v1/visguard/jobs/{job_id}/events', timeout=10,
    )
    assert stream.status_code == 200
    assert stream.headers['content-type'].startswith('text/event-stream')
    body = stream.text
    assert body
    assert 'event: completed' in body