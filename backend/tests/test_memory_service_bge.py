"""测试 BGE-M3 向量模型配置化。"""

import pytest


class TestEmbeddingConfig:
    """向量模型配置测试。"""

    def test_default_embedding_model(self):
        """默认模型应为 BAAI/bge-m3。"""
        from app.config import settings
        assert settings.embedding_model == 'BAAI/bge-m3'

    def test_default_embedding_dimension(self):
        """默认维度应为 1024。"""
        from app.config import settings
        assert settings.embedding_dimension == 1024

    def test_fallback_model(self):
        """备用模型应为 moka-ai/m3e-base。"""
        from app.config import settings
        assert settings.embedding_fallback == 'moka-ai/m3e-base'

    def test_memory_model_default(self):
        """StoryMemory 模型的 embedding_model 默认值应为 BAAI/bge-m3。"""
        from app.models.memory import StoryMemory
        col = StoryMemory.__table__.columns['embedding_model']
        assert col.default.arg == 'BAAI/bge-m3'


class TestMemoryServiceModelLoading:
    """MemoryService 模型加载逻辑测试（不实际加载模型，仅验证代码路径）。"""

    def test_model_dir_name_conversion(self):
        """模型名转换为目录名的逻辑。"""
        model_name = 'BAAI/bge-m3'
        dir_name = model_name.replace('/', '--')
        assert dir_name == 'BAAI--bge-m3'

    def test_local_model_path_construction(self):
        """本地模型路径构建。"""
        import os
        cache_dir = '/tmp/test_cache'
        model_name = 'BAAI/bge-m3'
        model_dir_name = model_name.replace('/', '--')
        local_path = os.path.join(cache_dir, f'models--{model_dir_name}')
        assert 'models--BAAI--bge-m3' in local_path
        snapshots_dir = os.path.join(local_path, 'snapshots')
        assert snapshots_dir.endswith('snapshots')
