"""测试 Settings 配置加载与默认值。"""



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

    def test_cors_credentials_default_true(self):
        from app.config import settings
        assert settings.cors_allow_credentials is True

    def test_cors_effective_no_wildcard(self):
        # 白名单来源：凭据开关保留配置值
        from app.config import Settings
        s = Settings(cors_origins=['http://localhost:3000'], cors_allow_credentials=True)
        assert s.effective_cors_origins == ['http://localhost:3000']
        assert s.effective_allow_credentials is True

    def test_cors_wildcard_forces_credentials_off(self):
        # 通配符与凭据互斥（浏览器规范）：含 '*' 时强制关闭 credentials
        from app.config import Settings
        s = Settings(cors_origins=['*'], cors_allow_credentials=True)
        assert s.effective_cors_origins == ['*']
        assert s.effective_allow_credentials is False

    def test_cors_wildcard_mixed_list(self):
        # 列表中混有 '*' 同样触发强制关闭
        from app.config import Settings
        s = Settings(cors_origins=['*', 'http://localhost:8000'])
        assert s.effective_cors_origins == ['*']
        assert s.effective_allow_credentials is False

    def test_visguard_new_fields_defaults(self):
        from app.config import settings
        # P0-3 NSFW 默认关闭（离线零成本放行）
        assert settings.visguard_content_safety_enabled is False
        assert settings.visguard_content_safety_device == 'cpu'
        assert settings.visguard_nsfw_threshold > 0
        # P0-4 成本预算默认不限额
        assert settings.visguard_cloud_max_daily_cost == 0.0

    def test_database_slow_query_threshold(self):
        from app.config import settings
        assert settings.database_slow_query_threshold > 0
