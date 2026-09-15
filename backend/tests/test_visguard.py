"""VisGuard 服务层 + 契约测试。

覆盖：
- core.exceptions：云端错误归一化 / 重试策略 / 幂等键（契约）
- core.cache：三级缓存命中、磁盘持久化、JSON 安全值约束、统计
- core.config_snapshot：配置快照字段（契约）
- generation：供应商能力矩阵、参数校验/降级、工厂回退
- CharacterBank：注册/查列/删除/追加图/相似度排序/阈值过滤
  （FakeClipEncoder 注入，避免真实模型下载；faiss 缺失时 importorskip 跳过）
"""

import io
import json

import pytest
from PIL import Image

import numpy as np

faiss = pytest.importorskip('faiss')  # faiss 为可选重依赖，缺失时整模块跳过

from app.config import settings  # noqa: E402
from app.services.visguard.character_bank import CharacterBank, CharacterNotFoundError  # noqa: E402
from app.services.visguard.core import exceptions as exc  # noqa: E402
from app.services.visguard.core.cache import CacheManager, CacheNamespace  # noqa: E402
from app.services.visguard.core.config_snapshot import (  # noqa: E402
    reset_for_tests,
    take_config_snapshot,
)
from app.services.visguard.generation import capabilities as gen_caps  # noqa: E402
from app.services.visguard.generation.factory import create_generator  # noqa: E402


# =============================================================================
# 测试替身
# =============================================================================

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


def _solid_image(rgb: tuple[int, int, int], size: int = 64) -> Image.Image:
    """生成纯色 RGB 图（不同颜色 → 不同灰度向量）。"""
    return Image.new('RGB', (size, size), rgb)


@pytest.fixture
def clip():
    return FakeClipEncoder()


@pytest.fixture
def bank(tmp_path, clip) -> CharacterBank:
    """临时目录角色库（index_root=tmp_path，不污染真实 DATA_DIR）。"""
    b = CharacterBank(
        project_id='test-project',
        base_dir=str(tmp_path),
        clip=clip,
        default_threshold=0.5,
    )
    yield b


# =============================================================================
# core.exceptions 契约
# =============================================================================

class TestCoreExceptions:
    def test_map_cloud_error_401_auth(self):
        e = exc.map_cloud_error(401, {'error': {'message': 'bad key', 'code': 'invalid_api_key'}})
        assert isinstance(e, exc.AuthError)
        assert e.status_code == 401
        assert e.code.startswith('auth_error') and 'invalid_api_key' in e.code

    def test_map_cloud_error_429_rate_limit(self):
        e = exc.map_cloud_error(429, {'error': {'message': 'slow down'}})
        assert isinstance(e, exc.RateLimitError)
        assert e.status_code == 429

    def test_map_cloud_error_5xx_provider(self):
        e = exc.map_cloud_error(503, {'error': {'message': 'boom'}})
        assert isinstance(e, exc.ProviderUnavailable)
        assert e.status_code == 503

    def test_retry_policy_matrix(self):
        assert exc.RETRY_POLICIES[exc.RateLimitError].max_retries == 3
        assert exc.RETRY_POLICIES[exc.RateLimitError].backoff == 'exponential'
        assert exc.RETRY_POLICIES[exc.ProviderUnavailable].max_retries == 2

    def test_get_idempotency_key_deterministic(self):
        p1 = {'prompt': 'a', 'seed': 1, 'width': 1024}
        p2 = {'width': 1024, 'seed': 1, 'prompt': 'a'}  # 键序不同
        assert exc.get_idempotency_key(p1) == exc.get_idempotency_key(p2)
        assert exc.get_idempotency_key(p1) != exc.get_idempotency_key({'prompt': 'b'})

    def test_error_hierarchy_str(self):
        e = exc.ClipUnavailableError('模型不可用')
        assert str(e) == 'clip_unavailable: 模型不可用'
        assert e.status_code == 503


# =============================================================================
# core.cache 契约
# =============================================================================

class TestCacheManager:
    def test_l1_get_set_and_stats(self, tmp_path):
        c = CacheManager(str(tmp_path / 'cache'))
        c.set(CacheNamespace.GENERATION, 'k1', {'a': 1})
        assert c.get(CacheNamespace.GENERATION, 'k1') == {'a': 1}
        stats = c.stats()
        assert stats['generation']['hits'] == 1
        assert stats['generation']['misses'] == 0
        assert stats['generation']['hit_rate'] == 1.0

    def test_l3_disk_persistence(self, tmp_path):
        d = str(tmp_path / 'cache')
        CacheManager(d).set(CacheNamespace.SIMILARITY, 'sk1', [1, 2, 3])
        # 新实例（清空内存）直接从磁盘命中
        c2 = CacheManager(d)
        assert c2.get(CacheNamespace.SIMILARITY, 'sk1') == [1, 2, 3]
        assert c2.stats()['similarity']['hits'] == 1

    def test_reject_non_json_value(self, tmp_path):
        c = CacheManager(str(tmp_path / 'cache'))
        with pytest.raises(ValueError):
            c.set(CacheNamespace.PREPROCESS, 'bad', object())

    def test_namespace_isolated(self, tmp_path):
        c = CacheManager(str(tmp_path / 'cache'))
        c.set(CacheNamespace.GENERATION, 'same', 'gen')
        # 不同命名空间同 key 互不干扰
        assert c.get(CacheNamespace.PREPROCESS, 'same') is None

    def test_cache_key_generation_stable(self):
        params = {'provider': 'sansi', 'model': 'm', 'prompt': 'p', 'seed': 1}
        from app.services.visguard.core.cache import CacheKey

        key_a = CacheKey.generation(params)
        key_b = CacheKey.generation(
            {'seed': 1, 'prompt': 'p', 'model': 'm', 'provider': 'sansi'}
        )
        assert key_a == key_b
        assert key_a != CacheKey.generation({'prompt': 'other'})


# =============================================================================
# core.config_snapshot 契约
# =============================================================================

class TestConfigSnapshot:
    def test_take_snapshot_fields(self):
        snap = take_config_snapshot()
        d = snap.to_dict()
        # 能力矩阵字段必须出现在快照中（前端协商依赖）
        assert 'embedding_backend' in d
        assert 'generate_backend' in d
        assert 'inspect_backend' in d
        assert 'default_threshold' in d
        # 模块级私有字段不导出（generation / 密钥哈希）
        assert 'generation' not in d
        assert 'cloud_api_key_hash' not in d
        assert snap.generation >= 0

    def test_reset_for_tests(self):
        assert reset_for_tests() is None


# =============================================================================
# generation 能力矩阵
# =============================================================================

class TestGenerationCapabilities:
    def test_producer_matrix_has_four_providers(self):
        assert set(gen_caps.PRODUCER_CAPABILITIES) == {'sansi', 'aliyun', 'tencent', 'openai'}

    def test_sansi_supports_ip_adapter_and_async(self):
        caps = gen_caps.get_provider_capabilities('sansi')
        assert caps.supports_ip_adapter is True
        assert caps.supports_async is True
        assert 'openpose' in caps.controlnet_types

    def test_unknown_provider_falls_back_safe(self):
        caps = gen_caps.get_provider_capabilities('nonexistent')
        assert caps.controlnet_types == []
        assert caps.supports_seed is True  # 保守默认不崩溃

    def test_validate_downgrades_unsupported_control(self):
        params = {'control_type': 'openpose', 'seed': 42}
        warnings = gen_caps.validate_generation_params('openai', params)
        # openai 无 controlnet → 降级 canny，warnings 非空
        assert warnings
        assert params['control_type'] == 'canny'

    def test_validate_keeps_supported_params(self):
        params = {'control_type': 'canny', 'seed': 7}
        warnings = gen_caps.validate_generation_params('sansi', params)
        assert warnings == []
        assert params['control_type'] == 'canny'
        assert params['seed'] == 7

    def test_validate_drops_seed_when_unsupported(self):
        params = {'seed': 3}
        warnings = gen_caps.validate_generation_params('aliyun', params)  # aliyun 不支持 seed
        assert warnings
        assert 'seed' not in params

    def test_create_generator_default_none(self):
        # 默认配置 generate_backend='none' → 无生成器（Post /jobs 应 503）
        assert create_generator() is None


# =============================================================================
# CharacterBank 集成（fake clip + 真实 faiss）
# =============================================================================

class TestCharacterBank:
    def test_register_and_list(self, bank):
        info = bank.register('主角', _solid_image((200, 30, 30)), '红衣')
        assert info['name'] == '主角'
        assert info['image_count'] == 1
        assert info['id']

        listed = bank.list_characters()
        assert len(listed) == 1
        assert listed[0]['embedding_count'] == 1
        assert bank.get(info['id'])['embedding_count'] == 1

    def test_register_different_images_different_vectors(self, bank):
        a = bank.register('甲', _solid_image((255, 0, 0)))
        b = bank.register('乙', _solid_image((0, 0, 255)))
        assert a['id'] != b['id']
        assert len(bank.list_characters()) == 2

    def test_add_image_increments_count(self, bank):
        cid = bank.register('主角', _solid_image((10, 200, 10)))['id']
        result = bank.add_image(cid, _solid_image((20, 200, 20), size=128))
        assert result['character_id'] == cid
        assert bank.get(cid)['embedding_count'] == 2
        assert bank.get(cid)['image_count'] == 2

    def test_add_image_missing_character(self, bank):
        with pytest.raises(CharacterNotFoundError):
            bank.add_image('nope', _solid_image((1, 2, 3)))

    def test_find_similar_ranks_by_score(self, bank):
        hero = bank.register('主角', _solid_image((240, 40, 40)))['id']
        bank.register('路人', _solid_image((40, 40, 240)))

        # 查询与主角同色 → 主角应排第一
        results = bank.find_similar(_solid_image((230, 50, 50)), top_k=5)
        assert results[0]['character_id'] == hero
        assert results[0]['score'] > 0.9  # 相同色块 → 余弦≈1 → 分数≈1
        assert all(
            results[i]['score'] >= results[i + 1]['score']
            for i in range(len(results) - 1)
        )

    def test_find_similar_threshold_filter(self, bank):
        bank.register('主角', _solid_image((240, 40, 40)))
        bank.register('路人', _solid_image((40, 40, 240)))
        # 高阈值（0.99）过滤掉所有低分结果（不同色块分数 < 0.99）
        results = bank.find_similar(_solid_image((10, 10, 10)), top_k=5, threshold=0.99)
        assert results == []

    def test_delete_removes_character(self, bank):
        cid = bank.register('主角', _solid_image((240, 40, 40)))['id']
        assert bank.delete(cid) is True
        assert bank.get(cid) is None
        assert bank.delete(cid) is False
        assert len(bank.list_characters()) == 0

    def test_embedding_persistence_across_reopen(self, tmp_path, clip):
        """重开银行（模拟服务重启）后向量仍在（FAISS + meta.json 持久化）。"""
        b1 = CharacterBank(
            project_id='persist-proj', base_dir=str(tmp_path),
            clip=clip, default_threshold=0.5,
        )
        cid = b1.register('主角', _solid_image((240, 40, 40)))['id']

        b2 = CharacterBank(
            project_id='persist-proj', base_dir=str(tmp_path),
            clip=clip, default_threshold=0.5,
        )
        assert b2.get(cid) is not None
        results = b2.find_similar(_solid_image((230, 50, 50)), top_k=5)
        assert results and results[0]['character_id'] == cid


# =============================================================================
# image_utils 契约
# =============================================================================

class TestImageUtils:
    def test_bytes_to_image_and_sha256(self):
        from app.services.visguard.image_utils import bytes_to_image, image_sha256

        buf = io.BytesIO()
        Image.new('RGB', (32, 32), (255, 0, 0)).save(buf, format='PNG')
        img = bytes_to_image(buf.getvalue())
        assert img.mode == 'RGB'
        h1 = image_sha256(img)
        assert len(h1) == 32  # 截断 sha256 hex（去重指纹）

    def test_invalid_bytes_raise_valueerror(self):
        from app.services.visguard.image_utils import bytes_to_image

        with pytest.raises(ValueError):
            bytes_to_image(b'not an image at all')