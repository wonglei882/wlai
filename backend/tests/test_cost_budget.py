"""成本预算测试（P0-4）。

覆盖:
- FileBudgetStorage：原子扣减/限额/持久化/重置/损坏文件容错/原子写（tmp+rename）
- CostBudget 控制器：不限额放行（不写盘）、限额扣减、超限拒绝、查询/重置
"""



from app.services.visguard.core.cost_budget import (
    CostBudget,
    FileBudgetStorage,
)


class TestFileBudgetStorage:
    def test_load_missing_returns_zero(self, tmp_path):
        storage = FileBudgetStorage(path=tmp_path / 'b.json')
        assert storage.load('2026-01-01') == 0.0

    def test_save_and_load(self, tmp_path):
        storage = FileBudgetStorage(path=tmp_path / 'b.json')
        storage.save('2026-01-01', 3.5)
        assert storage.load('2026-01-01') == 3.5

    def test_atomic_add_within_limit(self, tmp_path):
        storage = FileBudgetStorage(path=tmp_path / 'b.json')
        ok, total = storage.atomic_add('2026-01-01', 2.0, 10.0)
        assert ok is True
        assert total == 2.0

    def test_atomic_add_exceeds_limit_rejected(self, tmp_path):
        storage = FileBudgetStorage(path=tmp_path / 'b.json')
        storage.save('2026-01-01', 9.0)
        ok, total = storage.atomic_add('2026-01-01', 2.0, 10.0)
        assert ok is False
        assert total == 9.0  # 未扣减，保持原值

    def test_atomic_add_unlimited(self, tmp_path):
        storage = FileBudgetStorage(path=tmp_path / 'b.json')
        ok, total = storage.atomic_add('2026-01-01', 1.5, 0.0)
        assert ok is True
        assert total == 1.5

    def test_atomic_add_non_positive_amount(self, tmp_path):
        storage = FileBudgetStorage(path=tmp_path / 'b.json')
        ok, total = storage.atomic_add('2026-01-01', 0.0, 10.0)
        assert ok is True

    def test_reset_day(self, tmp_path):
        storage = FileBudgetStorage(path=tmp_path / 'b.json')
        storage.save('2026-01-01', 5.0)
        storage.reset_day('2026-01-01')
        assert storage.load('2026-01-01') == 0.0

    def test_persistence_across_instances(self, tmp_path):
        path = tmp_path / 'b.json'
        FileBudgetStorage(path=path).save('2026-01-01', 7.25)
        # 新实例读取同一文件
        storage2 = FileBudgetStorage(path=path)
        assert storage2.load('2026-01-01') == 7.25

    def test_corrupted_file_recovers(self, tmp_path):
        path = tmp_path / 'b.json'
        path.write_text('{not-json', encoding='utf-8')
        storage = FileBudgetStorage(path=path)  # 不 crash，重建空账本
        assert storage.load('2026-01-01') == 0.0

    def test_atomic_write_no_tmp_leftover(self, tmp_path):
        path = tmp_path / 'b.json'
        storage = FileBudgetStorage(path=path)
        storage.save('2026-01-01', 1.0)
        assert not (tmp_path / 'b.json.tmp').exists()  # tmp 必须已 rename
        assert path.exists()


class TestCostBudget:
    def test_unlimited_skips_storage(self, tmp_path):
        storage = FileBudgetStorage(path=tmp_path / 'b.json')
        budget = CostBudget(daily_max=0.0, storage=storage)
        ok, total = budget.try_charge(5.0)
        assert ok is True
        assert total == 0.0  # 不限额不记录
        assert storage.load('2026-01-01') == 0.0

    def test_charge_within_limit(self, tmp_path):
        budget = CostBudget(daily_max=10.0, storage=FileBudgetStorage(path=tmp_path / 'b.json'))
        ok, total = budget.try_charge(3.0)
        assert ok is True
        assert total == 3.0
        assert budget.today_used() == 3.0

    def test_charge_over_limit_rejected(self, tmp_path):
        budget = CostBudget(daily_max=1.0, storage=FileBudgetStorage(path=tmp_path / 'b.json'))
        ok, _ = budget.try_charge(0.6)
        assert ok is True
        ok, used = budget.try_charge(0.6)  # 0.6+0.6 > 1.0
        assert ok is False
        assert used == 0.6

    def test_reset_today(self, tmp_path):
        budget = CostBudget(daily_max=10.0, storage=FileBudgetStorage(path=tmp_path / 'b.json'))
        budget.try_charge(4.0)
        assert budget.today_used() == 4.0
        budget.reset_today()
        assert budget.today_used() == 0.0

    def test_unlimited_today_used_zero(self, tmp_path):
        budget = CostBudget(daily_max=0.0, storage=FileBudgetStorage(path=tmp_path / 'b.json'))
        assert budget.today_used() == 0.0
        budget.try_charge(9.0)
        assert budget.today_used() == 0.0