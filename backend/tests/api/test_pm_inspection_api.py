"""PM 主动巡检 API 集成测试 — GET /api/pm/inspect/{project_id}?user_id=xxx。

覆盖：
- 健康项目：score=10.0、issues/warnings 为空、suggestions 提示健康；
- 低质量章节检出：直插 PlotAnalysis(overall_quality_score=2.0) → issue 'low_quality_chapter'
  （critical，score 降至 3.0），suggestions 给出 high 优先级处理建议；
- 高频失败模式检出：直插 FailurePattern(occurrence_count>=3) → warning + score 降至 7.0；
- 项目不存在 → 404、非归属 → 403（细则在 test_projects_api.py 覆盖）。
"""

import uuid

# 与 conftest 中 dependency_overrides 的固定用户一致
TEST_USER_ID = 'u_test_api_user'


async def _inspect(client, project_id, user_id=TEST_USER_ID):
    resp = await client.get(f'/api/pm/inspect/{project_id}', params={'user_id': user_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_inspect_healthy_project(api_env, seed_project):
    """无任何 PM 数据的项目 → 健康报告。"""
    client, _ = api_env
    project_id = await seed_project()

    data = await _inspect(client, project_id)
    assert data['status'] == 'ok'
    report = data['report']
    assert report['project_id'] == project_id
    assert report['overall_health_score'] == 10.0
    assert report['issues'] == []
    assert report['warnings'] == []
    assert report['suggestions']
    assert report['suggestions'][0]['priority'] == 'low'
    assert report['suggestions'][0]['title'] == '项目 PM 状态健康'


async def test_inspect_detects_low_quality_chapter(api_env, seed_project):
    """PlotAnalysis 评分 2.0（<3.0）→ critical issue，score 降至 3.0。"""
    from app.models.chapter import Chapter
    from app.models.memory import PlotAnalysis

    client, Session = api_env
    project_id = await seed_project()

    # 直插 chapter（PlotAnalysis.chapter_id 为 NOT NULL FK）
    async with Session() as s:
        chapter_id = str(uuid.uuid4())
        s.add(Chapter(
            id=chapter_id,
            project_id=project_id,
            chapter_number=1,
            title='第一章',
            content='正文',
            summary='',
            word_count=2,
            status='draft',
        ))
        s.add(PlotAnalysis(
            id=str(uuid.uuid4()),
            project_id=project_id,
            chapter_id=chapter_id,
            plot_stage='发展',
            overall_quality_score=2.0,
            pacing='中速',
            analysis_report='情节推进偏弱，冲突不足。',
        ))
        await s.commit()

    data = await _inspect(client, project_id)
    report = data['report']
    assert report['overall_health_score'] == 3.0
    assert len(report['issues']) == 1
    issue = report['issues'][0]
    assert issue['type'] == 'low_quality_chapter'
    assert issue['severity'] == 'critical'
    assert issue['chapter_id'] == chapter_id

    # suggestions 应含 high 优先级的低质量处理建议
    high = [sg for sg in report['suggestions'] if sg['priority'] == 'high']
    assert high and high[0]['title'] == '优先处理低质量章节'


async def test_inspect_detects_failure_pattern(api_env, seed_project):
    """FailurePattern occurrence_count>=3 → warning，score 降至 7.0。"""
    from app.models.pm_v2 import FailurePattern

    client, Session = api_env
    project_id = await seed_project()

    async with Session() as s:
        s.add(FailurePattern(
            id=str(uuid.uuid4()),
            project_id=project_id,
            pattern_type='pov_switch',
            occurrence_count=5,
            error_description='视角频繁切换导致叙事混乱',
            root_cause='大纲未锁定视角',
            recovery_suggestion='锁定第一人称视角',
        ))
        await s.commit()

    data = await _inspect(client, project_id)
    report = data['report']
    assert report['overall_health_score'] == 7.0
    assert len(report['warnings']) == 1
    warning = report['warnings'][0]
    assert warning['type'] == 'failure_pattern'
    assert warning['severity'] == 'warning'

    medium = [sg for sg in report['suggestions'] if sg['priority'] == 'medium']
    assert medium and medium[0]['title'] == '重复失败模式需系统性修复'


async def test_inspect_project_not_found_404(api_env):
    """巡检不存在的项目 → 404（归属校验前置）。"""
    client, _ = api_env
    resp = await client.get(
        f'/api/pm/inspect/{uuid.uuid4()}',
        params={'user_id': TEST_USER_ID},
    )
    assert resp.status_code == 404
    assert resp.json()['error'] == '项目不存在'


async def test_inspect_other_users_project_403(api_env, seed_project):
    """巡检非当前用户的项目 → 403。"""
    client, _ = api_env
    other_project = await seed_project(user_id='u_test_api_other', title='他人项目')

    resp = await client.get(
        f'/api/pm/inspect/{other_project}',
        params={'user_id': TEST_USER_ID},
    )
    assert resp.status_code == 403
    assert resp.json()['error'] == '无权访问此项目 PM 数据'