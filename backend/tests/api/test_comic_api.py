"""漫剧分镜 API 集成测试 — /api/v1/comic/* 分镜生成 + 镜头状态流转 + 素材 + 审核。

覆盖：
- 分镜生成：AI 失败 → 规则回退（确定性，无外部依赖）；shot 初始 pending_script；
- 分镜确认：confirm 批量推进 pending_script → pending_image（软警告放行）；
- 镜头状态流转：合法链路 7 态走通；跨态非法跳转 → 422；
- 事中门控：pending_review_image → pending_video 无 approved 首帧审核 → 400 拦截；
  创建 first_frame 审核并 approved 后放行（human-in-the-loop 核心环节）；
- 素材：多版本 version 递增；image 素材注册自动跑一致性门控并回写 gate；
- 审核：创建 pending → 更新 approved → 列表可见。
"""

import uuid

# 与 conftest 中 dependency_overrides 的固定用户一致
TEST_USER_ID = 'u_test_api_user'


async def _generate_storyboard(client, project_id, text='主角推开大门。敌人从阴影中现身。'):
    """POST /storyboards/generate 并断言 200，返回响应 json。"""
    resp = await client.post('/api/v1/comic/storyboards/generate', json={
        'project_id': project_id,
        'text': text,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _get_storyboard_shots_with_id(client, sb_id):
    """GET /storyboards/{id} 返回 shots（含 shotgun id 的完整字段）。"""
    resp = await client.get(f'/api/v1/comic/storyboards/{sb_id}')
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _force_rules_mode(monkeypatch):
    """强制 StoryboardGenerator 走规则回退（AI 抛异常 → 回退 rules 路径）。"""
    from app.services.comic.storyboard_gen import StoryboardGenerator

    async def _raise_ai(*args, **kwargs):
        raise RuntimeError('AI 不可用（测试强制走规则回退）')

    monkeypatch.setattr(StoryboardGenerator, '_generate_with_ai', _raise_ai)


async def test_generate_storyboard_rules_fallback(api_env, seed_project, monkeypatch):
    """生成分镜：AI 失败回退规则版 → 200，2 句文本 → 2 shot，初始 pending_script。"""
    await _force_rules_mode(monkeypatch)
    client, _ = api_env
    project_id = await seed_project()

    data = await _generate_storyboard(client, project_id)
    assert data['shot_count'] == 2
    assert data['status'] == 'draft'
    assert len(data['shots']) == 2
    assert all(s['status'] == 'pending_script' for s in data['shots'])
    assert all(s['shot_number'] == i for i, s in enumerate(data['shots'], start=1))


async def test_get_storyboard_returns_shot_ids(api_env, seed_project, monkeypatch):
    """生成后详情接口返回镜头完整字段（含 id），供后续流转使用。"""
    await _force_rules_mode(monkeypatch)
    client, _ = api_env
    project_id = await seed_project()

    gen = await _generate_storyboard(client, project_id)
    sb_id = gen['storyboard_id']

    detail = await _get_storyboard_shots_with_id(client, sb_id)
    assert detail['id'] == sb_id
    assert detail['project_id'] == project_id
    assert detail['shot_count'] == 2
    assert all(s['id'] for s in detail['shots'])
    assert all(s['status'] == 'pending_script' for s in detail['shots'])


async def test_confirm_storyboard_advances_shots(api_env, seed_project, monkeypatch):
    """confirm → 200 confirmed，镜头批量推进到 pending_image。"""
    await _force_rules_mode(monkeypatch)
    client, _ = api_env
    project_id = await seed_project()

    gen = await _generate_storyboard(client, project_id)
    sb_id = gen['storyboard_id']

    resp = await client.post(f'/api/v1/comic/storyboards/{sb_id}/confirm')
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data['status'] == 'confirmed'
    assert data['gate']['passed'] is True

    detail = await _get_storyboard_shots_with_id(client, sb_id)
    assert all(s['status'] == 'pending_image' for s in detail['shots'])


async def test_shot_status_legal_flow(api_env, seed_project, monkeypatch):
    """镜头状态流转合法链路全走通（含审核解锁后过首帧门控）。"""
    await _force_rules_mode(monkeypatch)
    client, _ = api_env
    project_id = await seed_project()

    gen = await _generate_storyboard(client, project_id)
    sb_id = gen['storyboard_id']
    detail = await _get_storyboard_shots_with_id(client, sb_id)
    shot_id = detail['shots'][0]['id']

    # pending_script → pending_image（gate: 无角色匹配 → 通过）
    r = await client.put(f'/api/v1/comic/shots/{shot_id}/status', json={'target_status': 'pending_image'})
    assert r.status_code == 200, r.text
    assert r.json()['current_status'] == 'pending_image'
    assert r.json()['gate']['passed'] is True

    # pending_image → pending_review_image（无图片素材 → 放行）
    r = await client.put(f'/api/v1/comic/shots/{shot_id}/status', json={'target_status': 'pending_review_image'})
    assert r.status_code == 200, r.text
    assert r.json()['current_status'] == 'pending_review_image'

    # pending_review_image → pending_video：无 approved first_frame 审核 → 400 拦截
    r = await client.put(f'/api/v1/comic/shots/{shot_id}/status', json={'target_status': 'pending_video'})
    assert r.status_code == 400, r.text
    assert r.json()['error']['message'] == '缺少首帧审核点'
    assert r.json()['error']['issues'][0]['type'] == 'ca_review_missing'

    # 创建 first_frame 审核并 approved
    rev = await client.post('/api/v1/comic/reviews', json={
        'project_id': project_id,
        'target_type': 'shot',
        'target_id': shot_id,
        'review_type': 'first_frame',
    })
    assert rev.status_code == 200, rev.text
    review_id = rev.json()['id']
    assert rev.json()['status'] == 'pending'

    approved = await client.put(f'/api/v1/comic/reviews/{review_id}', json={
        'status': 'approved',
        'reviewer_notes': '首帧构图通过',
        'reviewed_by': TEST_USER_ID,
    })
    assert approved.status_code == 200, approved.text
    assert approved.json()['status'] == 'approved'

    # 审核通过后 → pending_video 放行
    r = await client.put(f'/api/v1/comic/shots/{shot_id}/status', json={'target_status': 'pending_video'})
    assert r.status_code == 200, r.text
    assert r.json()['current_status'] == 'pending_video'

    # 剩余链路：pending_voice → pending_composite → completed
    for target in ('pending_voice', 'pending_composite', 'completed'):
        r = await client.put(f'/api/v1/comic/shots/{shot_id}/status', json={'target_status': target})
        assert r.status_code == 200, f'{target}: {r.text}'
        assert r.json()['current_status'] == target


async def test_shot_status_illegal_transition_422(api_env, seed_project, monkeypatch):
    """非法跨状态跳转（pending_script → completed）→ 422 validation error。"""
    await _force_rules_mode(monkeypatch)
    client, _ = api_env
    project_id = await seed_project()

    gen = await _generate_storyboard(client, project_id)
    sb_id = gen['storyboard_id']
    detail = await _get_storyboard_shots_with_id(client, sb_id)
    shot_id = detail['shots'][0]['id']

    r = await client.put(f'/api/v1/comic/shots/{shot_id}/status', json={'target_status': 'completed'})
    assert r.status_code == 422, r.text
    assert r.json()['error'] == 'validation_error'


async def test_shot_status_not_found_404(api_env):
    """更新不存在的镜头 → 404。"""
    client, _ = api_env
    r = await client.put(f'/api/v1/comic/shots/{uuid.uuid4()}/status', json={'target_status': 'pending_image'})
    assert r.status_code == 404
    assert r.json()['error'] == 'not_found'


async def test_asset_upload_version_history(api_env, seed_project, monkeypatch):
    """素材上传：同镜头同类型 version 递增，GET 列表可见，image 触发一致性门控。"""
    await _force_rules_mode(monkeypatch)
    client, _ = api_env
    project_id = await seed_project()

    gen = await _generate_storyboard(client, project_id)
    sb_id = gen['storyboard_id']
    detail = await _get_storyboard_shots_with_id(client, sb_id)
    shot_id = detail['shots'][0]['id']

    a1 = await client.post('/api/v1/comic/assets', json={
        'shot_id': shot_id,
        'project_id': project_id,
        'asset_type': 'image',
        'file_url': 'https://cdn.example.com/frame_v1.png',
        'prompt_used': '测试提示词 v1',
        'parameters': {'seed': 42},
    })
    assert a1.status_code == 200, a1.text
    assert a1.json()['version'] == 1
    assert a1.json()['status'] == 'created'

    a2 = await client.post('/api/v1/comic/assets', json={
        'shot_id': shot_id,
        'project_id': project_id,
        'asset_type': 'image',
        'file_url': 'https://cdn.example.com/frame_v2.png',
        'prompt_used': '测试提示词 v2',
        'parameters': {'seed': 99},
    })
    assert a2.status_code == 200, a2.text
    assert a2.json()['version'] == 2

    lst = await client.get('/api/v1/comic/assets', params={'shot_id': shot_id})
    assert lst.status_code == 200
    data = lst.json()
    assert data['total'] == 2
    assert {a['version'] for a in data['assets']} == {1, 2}


async def test_reviews_list_and_filters(api_env, seed_project, monkeypatch):
    """审核点列表 → total 与项目过滤正确。"""
    await _force_rules_mode(monkeypatch)
    client, _ = api_env
    project_id = await seed_project()

    gen = await _generate_storyboard(client, project_id)
    detail = await _get_storyboard_shots_with_id(client, gen['storyboard_id'])
    shot_id = detail['shots'][0]['id']

    for _ in range(2):
        r = await client.post('/api/v1/comic/reviews', json={
            'project_id': project_id,
            'target_type': 'shot',
            'target_id': shot_id,
            'review_type': 'first_frame',
        })
        assert r.status_code == 200

    lst = await client.get('/api/v1/comic/reviews', params={'project_id': project_id})
    assert lst.status_code == 200
    data = lst.json()
    assert data['total'] == 2
    assert all(v['project_id'] == project_id for v in data['reviews'])
    assert all(v['status'] == 'pending' for v in data['reviews'])