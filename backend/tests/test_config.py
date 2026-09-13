"""测试 Settings 配置加载与默认值。"""

import pytest
from unittest.mock import patch


class TestSettingsDefaults:
    """Settings 默认值测试。"""

    def test_default_ai_provider(self):
        from app.config import settings
        assert settings.default_ai_provider == 'openai'

    def test_default_model(self):
        from app.config import settings
        assert settings.default_model == 'gpt-4'

    def test_default_temperature(self):
        from app.config import settings
        assert 0 <= settings.default_temperature <= 2

    def test_default_max_tokens(self):
        from app.config import settings
        assert settings.default_max_tokens > 0

    def test_embedding_model_default(self):
        from app.config import settings
        assert settings.embedding_model == 'BAAI/bge-m3'

    def test_embedding_dimension_default(self):
        from app.config import settings
        assert settings.embedding_dimension == 1024

    def test_multimodal_backend_default(self):
        from app.config import settings
        assert settings.multimodal_backend == 'none'

    def test_multimodal_cloud_provider_default(self):
        from app.config import settings
        assert settings.multimodal_cloud_provider == 'openai'

    def test_mcp_max_rounds_default(self):
        from app.config import settings
        assert settings.mcp_max_rounds >= 1

    def test_session_expire_minutes(self):
        from app.config import settings
        assert settings.SESSION_EXPIRE_MINUTES > 0

    def test_cors_origins_type(self):
        from app.config import settings
        assert isinstance(settings.cors_origins, list)

    def test_database_slow_query_threshold(self):
        from app.config import settings
        assert settings.database_slow_query_threshold > 0
