"""T3: PM 巡检按项目类型过滤维度测试（P0-3）。

覆盖：
- novel 项目不跑 comic 维度、comic 项目不跑 novel 维度
- universal 维度对两种项目恒跑
- 未知 genre（None）全跑（兼容旧数据）
- domain 元数据注册完整性（scan_dimension 写入 'domain' 字段）
"""
import uuid

from app.models.project import Project
from app.services.pm import pm_agent
from app.services.pm.pm_scanners import SCAN_REGISTRY

USER_ID = 'user_domain_filter'


async def _make_project(db, genre=None):
    p = Project(id=str(uuid.uuid4()), user_id=USER_ID, title='域名过滤测试', genre=genre)
    db.add(p)
    await db.commit()
    return p.id


def _spy_dim(name: str, called: list):
    async def fn(db, project_id, user_id):
        called.append(name)
        return []

    return fn


def _build_registry(called: list) -> dict:
    """迷你注册表：novel 2 维 + comic 2 维 + universal 1 维（spy 函数）。"""
    novel_dims = ['character_consistency', 'foreshadow_age']
    comic_dims = ['visual_consistency', 'scene_continuity']
    registry = {}
    for n in novel_dims:
        registry[n] = {
            'fn': _spy_dim(n, called),
            'issue_type': f'pm_agent_{n}',
            'diag_msg_fn': lambda i: f'issue {i}',
            'domain': 'novel',
        }
    for n in comic_dims:
        registry[n] = {
            'fn': _spy_dim(n, called),
            'issue_type': f'ca_{n}',
            'diag_msg_fn': lambda i: f'issue {i}',
            'domain': 'comic',
        }
    registry['universal_dim'] = {
        'fn': _spy_dim('universal_dim', called),
        'issue_type': 'pm_agent_universal',
        'diag_msg_fn': lambda i: f'issue {i}',
        'domain': 'universal',
    }
    return registry


async def _patch_scan_env(monkeypatch, called: list):
    """替换 SCAN_REGISTRY + 依赖辅助函数，让 _scan_single_project 只跑 spy 维度。"""
    monkeypatch.setattr(pm_agent, 'SCAN_REGISTRY', _build_registry(called))

    async def passthru(db, project_id, name, scanned):
        return scanned

    async def noop_evolve(db, project_id, issues, scan_round):
        pass

    monkeypatch.setattr(pm_agent, 'is_dimension_throttled', lambda project_id, name: False)
    monkeypatch.setattr(pm_agent, 'filter_exclusions', passthru)
    monkeypatch.setattr(pm_agent, 'evolve_after_round', noop_evolve)


class TestScanDomainRegistry:
    """domain 元数据注册完整性。"""

    def test_all_registered_dims_have_domain(self):
        for name, entry in SCAN_REGISTRY.items():
            assert entry.get('domain') in ('novel', 'comic', 'universal'), f'{name} 缺 domain 字段'
            assert callable(entry.get('fn'))
            assert entry.get('issue_type')
            assert callable(entry.get('diag_msg_fn'))

    def test_novel_dims_labelled_novel(self):
        novel_dims = {
            'character_consistency',
            'foreshadow_age',
            'world_rule_drift',
            'outline_drift',
            'quality_score',
            'paragraph_format',
        }
        for n in novel_dims:
            assert SCAN_REGISTRY[n]['domain'] == 'novel', f'{n} 应标注 novel'

    def test_comic_dims_labelled_comic(self):
        comic_dims = {'visual_consistency', 'scene_continuity', 'panel_transition', 'dialogue_bubble'}
        for n in comic_dims:
            assert SCAN_REGISTRY[n]['domain'] == 'comic', f'{n} 应标注 comic'


class TestScanSingleProjectGenreFilter:
    """_scan_single_project 按 Project.genre 过滤维度。"""

    async def test_novel_project_skips_comic_dims(self, db_session, monkeypatch):
        pid = await _make_project(db_session, genre='novel')
        called = []
        await _patch_scan_env(monkeypatch, called)

        result = await pm_agent._scan_single_project(db_session, pid, USER_ID)

        assert called == ['character_consistency', 'foreshadow_age', 'universal_dim'], (
            f'novel 项目应只跑 novel + universal 维度，实际: {called}'
        )
        # 被过滤的 comic 维度在 all_issues 中为空列表（不参与诊断/决策）
        assert result['issues']['visual_consistency'] == []
        assert result['issues']['scene_continuity'] == []

    async def test_comic_project_skips_novel_dims(self, db_session, monkeypatch):
        pid = await _make_project(db_session, genre='comic')
        called = []
        await _patch_scan_env(monkeypatch, called)

        result = await pm_agent._scan_single_project(db_session, pid, USER_ID)

        assert called == ['visual_consistency', 'scene_continuity', 'universal_dim'], (
            f'comic 项目应只跑 comic + universal 维度，实际: {called}'
        )
        assert result['issues']['character_consistency'] == []
        assert result['issues']['foreshadow_age'] == []

    async def test_unknown_genre_runs_all_dims(self, db_session, monkeypatch):
        """genre 为 NULL（旧数据/未知）→ 不过滤，全维度都跑（兼容现状）。"""
        pid = await _make_project(db_session, genre=None)
        called = []
        await _patch_scan_env(monkeypatch, called)

        await pm_agent._scan_single_project(db_session, pid, USER_ID)

        assert set(called) == {'character_consistency', 'foreshadow_age', 'visual_consistency', 'scene_continuity', 'universal_dim'}, (
            f'未知 genre 应全跑，实际: {called}'
        )

    async def test_universal_dim_always_runs(self, db_session, monkeypatch):
        """universal 维度对 novel/comic 两种项目都执行。"""
        for genre in ('novel', 'comic'):
            pid = await _make_project(db_session, genre=genre)
            called = []
            await _patch_scan_env(monkeypatch, called)

            await pm_agent._scan_single_project(db_session, pid, USER_ID)

            assert 'universal_dim' in called, f'{genre} 项目应跑 universal 维度，实际: {called}'