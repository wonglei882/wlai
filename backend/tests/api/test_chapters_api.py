"""章节 API 集成测试 — /api/v1/novel/chapters 全链路 CRUD。

覆盖：创建（102 参数校验/409 重复章号）、列表（按项目隔离、按章号排序）、
详情（404）、更新（word_count 重算）、删除（软性后端删除 → 再查 404）。
全部走真实 ASGI app（httpx ASGITransport）+ 依赖覆盖（固定测试用户 + 内存库）。
"""


async def _create_chapter(client, seed_project, number, title='第一章', content='内容'):
    project_id = await seed_project()
    resp = await client.post('/api/v1/novel/chapters', json={
        'project_id': project_id,
        'chapter_number': number,
        'title': title,
        'content': content,
    })
    return project_id, resp


async def test_create_chapter_success(api_env, seed_project):
    """创建章节 → 200，word_count=len(content)，status 默认 draft。"""
    client, _ = api_env
    project_id = await seed_project()
    resp = await client.post('/api/v1/novel/chapters', json={
        'project_id': project_id,
        'chapter_number': 1,
        'title': '第一章 风起',
        'content': '这是正文内容，一共二十个字符整。',
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data['project_id'] == project_id
    assert data['chapter_number'] == 1
    assert data['title'] == '第一章 风起'
    assert data['word_count'] == len('这是正文内容，一共二十个字符整。')
    assert data['status'] == 'draft'
    assert data['outline_id'] is None
    assert data['id']


async def test_create_chapter_duplicate_409(api_env, seed_project):
    """同项目重复章号 → 409。"""
    client, _ = api_env
    project_id = await seed_project()
    body = {
        'project_id': project_id,
        'chapter_number': 3,
        'title': '第三章',
        'content': '正文',
    }
    r1 = await client.post('/api/v1/novel/chapters', json=body)
    assert r1.status_code == 200
    r2 = await client.post('/api/v1/novel/chapters', json=body)
    assert r2.status_code == 409
    assert r2.json()['error'] == '第 3 章已存在'


async def test_create_chapter_chapter_number_ge1(api_env, seed_project):
    """chapter_number < 1 → 422（pydantic ge=1）。"""
    client, _ = api_env
    project_id = await seed_project()
    resp = await client.post('/api/v1/novel/chapters', json={
        'project_id': project_id,
        'chapter_number': 0,
        'title': '非法章节',
        'content': '正文',
    })
    assert resp.status_code == 422


async def test_list_and_sort_chapters(api_env, seed_project):
    """列表 → total 正确、按 chapter_number 升序、仅返回本项目。"""
    client, _ = api_env
    project_a = await seed_project()
    project_b = await seed_project()

    for n in (3, 1, 2):
        await client.post('/api/v1/novel/chapters', json={
            'project_id': project_a,
            'chapter_number': n,
            'title': f'第{n}章',
            'content': f'正文{n}',
        })
    # 项目B一条
    await client.post('/api/v1/novel/chapters', json={
        'project_id': project_b,
        'chapter_number': 1,
        'title': 'B章节',
        'content': 'B正文',
    })

    lst = await client.get('/api/v1/novel/chapters', params={'project_id': project_a})
    assert lst.status_code == 200
    data = lst.json()
    assert data['total'] == 3
    assert [c['chapter_number'] for c in data['chapters']] == [1, 2, 3]
    assert all(c['project_id'] == project_a for c in data['chapters'])


async def test_get_chapter_detail_and_404(api_env, seed_project):
    """详情 → 200 含 content；不存在 → 404。"""
    client, _ = api_env
    project_id = await seed_project()
    created = (await client.post('/api/v1/novel/chapters', json={
        'project_id': project_id,
        'chapter_number': 1,
        'title': '第一章',
        'content': '详情正文',
    })).json()
    cid = created['id']

    detail = await client.get(f'/api/v1/novel/chapters/{cid}')
    assert detail.status_code == 200
    assert detail.json()['content'] == '详情正文'

    missing = await client.get('/api/v1/novel/chapters/not-exist-id')
    assert missing.status_code == 404
    assert missing.json()['error'] == '章节不存在'


async def test_update_chapter_recomputes_word_count(api_env, seed_project):
    """PUT 更新 title/content → word_count 按新 content 重算。"""
    client, _ = api_env
    project_id = await seed_project()
    created = (await client.post('/api/v1/novel/chapters', json={
        'project_id': project_id,
        'chapter_number': 1,
        'title': '旧标题',
        'content': '旧正文',
    })).json()
    cid = created['id']

    resp = await client.put(f'/api/v1/novel/chapters/{cid}', json={
        'title': '新标题',
        'content': '新正文内容，更长的一段文本内容。',
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data['title'] == '新标题'
    assert data['content'] == '新正文内容，更长的一段文本内容。'
    assert data['word_count'] == len('新正文内容，更长的一段文本内容。')

    # 更新不存在章节 → 404
    missing = await client.put('/api/v1/novel/chapters/not-exist-id', json={'title': 'x'})
    assert missing.status_code == 404


async def test_delete_chapter(api_env, seed_project):
    """DELETE → {ok: True}；再查 → 404。"""
    client, _ = api_env
    project_id = await seed_project()
    created = (await client.post('/api/v1/novel/chapters', json={
        'project_id': project_id,
        'chapter_number': 1,
        'title': '待删除',
        'content': '正文',
    })).json()
    cid = created['id']

    resp = await client.delete(f'/api/v1/novel/chapters/{cid}')
    assert resp.status_code == 200
    assert resp.json() == {'ok': True}

    after = await client.get(f'/api/v1/novel/chapters/{cid}')
    assert after.status_code == 404

    missing = await client.delete('/api/v1/novel/chapters/not-exist-id')
    assert missing.status_code == 404