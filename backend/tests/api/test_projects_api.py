"""项目维度 API 集成测试。

注：当前代码库没有项目 CRUD API 路由（grep 证实：无 POST/GET/PUT/DELETE /projects）。
因此本文件覆盖「项目作为数据链路的根」这一实际能力：
- DB 直插 Project（seed_project fixture）后，章节/分镜可挂靠到该项目（外键链路成立）；
- 项目归属校验（_validate_project_ownership → 404/403）在 PM 巡检 API 中生效。
task_plan 中「项目 CRUD」的需求以「项目是下游链路的外键前提」方式验证，差异见 task7-report。
"""

import uuid

# 与 conftest 中 dependency_overrides 的固定用户一致
TEST_USER_ID = 'u_test_api_user'
OTHER_USER_ID = 'u_test_api_other'


async def test_project_seed_and_chapter_link(api_env, seed_project):
    """直插项目 → 章节创建挂靠该项目 → 章节列表按项目隔离。"""
    client, _ = api_env
    project_a = await seed_project(user_id=TEST_USER_ID, title='项目A')

    # 给项目A创建两个章节
    r1 = await client.post('/api/v1/novel/chapters', json={
        'project_id': project_a,
        'chapter_number': 1,
        'title': '第一章',
        'content': '正文内容一。',
    })
    assert r1.status_code == 200
    r2 = await client.post('/api/v1/novel/chapters', json={
        'project_id': project_a,
        'chapter_number': 2,
        'title': '第二章',
        'content': '正文内容二。',
    })
    assert r2.status_code == 200

    # 列表返回该项目 2 章，按 chapter_number 升序
    lst = await client.get('/api/v1/novel/chapters', params={'project_id': project_a})
    assert lst.status_code == 200
    data = lst.json()
    assert data['total'] == 2
    assert [c['chapter_number'] for c in data['chapters']] == [1, 2]
    assert all(c['project_id'] == project_a for c in data['chapters'])


async def test_project_isolation_between_users(api_env, seed_project):
    """不同用户的项目互不可见：B 用户项目在 A 用户视角不可访问。"""
    client, _ = api_env
    other_project = await seed_project(user_id=OTHER_USER_ID, title='他人项目')

    # 章节列表只按 project_id 过滤，不校验归属（挂靠成功与否由下游决定）；
    # 归属硬校验体现在 PM 巡检 API：用当前用户查他人项目 → 403
    resp = await client.get(
        f'/api/pm/inspect/{other_project}',
        params={'user_id': TEST_USER_ID},
    )
    assert resp.status_code == 403
    assert resp.json()['error'] == '无权访问此项目 PM 数据'


async def test_project_seed_and_comic_bind(api_env, seed_project, monkeypatch):
    """直插项目 → 分镜生成挂靠该项目（storyboard.project_id 正确落库）。"""
    from app.services.comic.storyboard_gen import StoryboardGenerator

    async def _raise_ai(*args, **kwargs):
        raise RuntimeError('AI 不可用（测试强制走规则回退）')

    monkeypatch.setattr(StoryboardGenerator, '_generate_with_ai', _raise_ai)

    client, _ = api_env
    project_id = await seed_project(user_id=TEST_USER_ID, title='漫剧项目')

    resp = await client.post('/api/v1/comic/storyboards/generate', json={
        'project_id': project_id,
        'text': '主角推开大门。敌人从阴影中现身。',
    })
    assert resp.status_code == 200
    data = resp.json()
    sb_id = data['storyboard_id']
    assert data['shot_count'] == 2
    assert data['status'] == 'draft'
    assert all(sh['status'] == 'pending_script' for sh in data['shots'])

    # 详情接口确认 storyboard.project_id 落库为该测试项目
    detail = await client.get(f'/api/v1/comic/storyboards/{sb_id}')
    assert detail.status_code == 200
    assert detail.json()['project_id'] == project_id


async def test_pm_inspect_project_not_found(api_env):
    """巡检不存在的项目 → 404。"""
    client, _ = api_env
    resp = await client.get(
        f'/api/pm/inspect/{uuid.uuid4()}',
        params={'user_id': TEST_USER_ID},
    )
    assert resp.status_code == 404
    assert resp.json()['error'] == '项目不存在'