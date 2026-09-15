"""工厂注册表测试（P0-2）。

覆盖:
- register/get 懒构建 + 实例复用
- reload 原子重建 + generation 递增
- reload 构建失败 → 回滚保留旧实例
- get 未注册 / 构建失败 → None（不抛错）
- reload_all / drop / registered
"""


from app.services.visguard.core.factory_registry import FactoryRegistry


def _counter_factory(store: dict):
    """每次调用递增的工厂，用于验证重建确实再次调用了工厂。"""
    def _make():
        store['calls'] = store.get('calls', 0) + 1
        return {'gen': store['calls']}
    return _make


class TestRegisterGet:
    def test_get_lazy_build(self):
        store = {}
        reg = FactoryRegistry()
        reg.register('a', _counter_factory(store))
        assert 'calls' not in store  # 未触发构建
        inst = reg.get('a')
        assert inst == {'gen': 1}
        assert store['calls'] == 1

    def test_instance_cached(self):
        store = {}
        reg = FactoryRegistry()
        reg.register('a', _counter_factory(store))
        assert reg.get('a') is reg.get('a')  # 同一实例
        assert store['calls'] == 1

    def test_get_unregistered_returns_none(self):
        reg = FactoryRegistry()
        assert reg.get('missing') is None

    def test_build_failure_returns_none(self):
        def _boom():
            raise RuntimeError('工厂失败')
        reg = FactoryRegistry()
        reg.register('bad', _boom)
        assert reg.get('bad') is None  # 不抛错

    def test_registered_sorted(self):
        reg = FactoryRegistry()
        reg.register('b', lambda: 1)
        reg.register('a', lambda: 2)
        assert reg.registered() == ['a', 'b']


class TestReload:
    def test_reload_rebuilds_and_bumps_generation(self):
        store = {}
        reg = FactoryRegistry()
        reg.register('a', _counter_factory(store))
        first = reg.get('a')
        assert reg.generation('a') == 0  # get 不算「成功重建」代次

        assert reg.reload('a') is True
        second = reg.get('a')
        assert second is not first
        assert second == {'gen': 2}
        assert reg.generation('a') == 1

    def test_reload_failure_keeps_old_instance(self):
        calls = {'n': 0}

        def _flaky():
            calls['n'] += 1
            if calls['n'] == 2:
                raise RuntimeError('第二次构建失败')
            return {'n': calls['n']}

        reg = FactoryRegistry()
        reg.register('a', _flaky)
        first = reg.get('a')
        assert first == {'n': 1}

        # reload 失败 → 回滚，保留旧实例
        ok = reg.reload('a')
        assert ok is False
        assert reg.get('a') is first
        assert reg.generation('a') == 0

        # 恢复后可重建
        ok = reg.reload('a')
        assert ok is True
        assert reg.get('a') == {'n': 3}

    def test_reload_unregistered_returns_false(self):
        reg = FactoryRegistry()
        assert reg.reload('ghost') is False

    def test_reload_all(self):
        reg = FactoryRegistry()
        reg.register('a', lambda: {'x': 1})
        reg.register('b', lambda: {'y': 2})
        results = reg.reload_all()
        assert results == {'a': True, 'b': True}
        assert reg.generation('a') == 1
        assert reg.generation('b') == 1

    def test_drop(self):
        reg = FactoryRegistry()
        reg.register('a', lambda: 1)
        assert reg.get('a') == 1
        reg.drop('a')
        assert reg.get('a') is None
        assert reg.registered() == []


class TestVisGuardIntegration:
    """VisGuardService 接入：generate 工厂经 registry 管理。"""

    def test_generate_registered(self):
        from app.config import settings
        from app.services.visguard import VisGuardService

        service = VisGuardService(
            clip_model='mock/model', clip_device='cpu', index_root='tmp-index',
        )
        try:
            assert 'generate' in service.registry.registered()
            gen = service.registry.get('generate')
            # generate_backend 配置决定实例存在性
            expected_none = settings.visguard_generate_backend == 'none'
            assert (gen is None) == expected_none
            assert 'generation' in service.status()['capabilities']['generate']
        finally:
            service.clip.unload()

    def test_reload_capabilities(self):
        from app.services.visguard import VisGuardService

        service = VisGuardService(
            clip_model='mock/model', clip_device='cpu', index_root='tmp-index',
        )
        try:
            results = service.reload_capabilities()
            assert 'generate' in results
            assert isinstance(results['generate'], bool)
        finally:
            service.clip.unload()