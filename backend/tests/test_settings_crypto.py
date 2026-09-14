"""Task 1 (P0-1): settings 敏感字段加密 — crypto 单元 + Settings 模型集成测试。

覆盖:
- Fernet 加密往返 / legacy 明文兼容 / 解密缓存
- Settings 模型 api_key / cover_api_key / smtp_password property 化（透明读写）
- 缺失 FERNET_KEY 时 fail-closed-on-use（读写非空值抛 RuntimeError，None 赋值不抛）
"""
import pytest
from app.core import crypto
from app.models.settings import Settings
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _clean_cache():
    """每个测试前清空进程级解密缓存，避免跨测试密钥串扰。"""
    crypto._decrypt_cache.clear()  # noqa: SLF001 - 测试直接操作缓存
    yield
    crypto._decrypt_cache.clear()  # noqa: SLF001


@pytest.fixture
def test_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def apply_key(monkeypatch, test_key: str):
    """把 FERNET_KEY 注入 app.config.settings（全局单例）。"""
    from app.config import settings

    monkeypatch.setattr(settings, 'FERNET_KEY', test_key)
    return test_key


# ──────────────── 单元测试: crypto.py ────────────────


class TestCrypto:
    def test_encrypt_decrypt_roundtrip(self, apply_key):
        plain = 'sk-test-123456'
        cipher = crypto.encrypt_api_key(plain)
        assert cipher != plain  # 真正加密
        assert crypto.decrypt_api_key(cipher) == plain

    def test_cipher_is_fernet_token(self, apply_key):
        cipher = crypto.encrypt_api_key('secret')
        assert cipher.startswith('gAAAA')  # Fernet token 前缀

    def test_legacy_plaintext_passthrough(self, apply_key):
        """存量明文（非 Fernet token）读取时原样返回。"""
        assert crypto.decrypt_api_key('sk-legacy-明文') == 'sk-legacy-明文'

    def test_decrypt_cache_hit(self, apply_key, monkeypatch):
        """缓存命中: 同一密文不应重复解密。"""
        cipher = crypto.encrypt_api_key('cache-me')
        import cryptography.fernet as fernet_mod

        calls = {'n': 0}
        original_decrypt = fernet_mod.Fernet.decrypt

        def spy_decrypt(self, token, **kwargs):
            calls['n'] += 1
            return original_decrypt(self, token, **kwargs)

        monkeypatch.setattr(fernet_mod.Fernet, 'decrypt', spy_decrypt)
        assert crypto.decrypt_api_key(cipher) == 'cache-me'
        assert crypto.decrypt_api_key(cipher) == 'cache-me'
        assert calls['n'] == 1  # 第二次命中缓存，未再解密

    def test_missing_key_raises_on_encrypt(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, 'FERNET_KEY', '')
        with pytest.raises(RuntimeError, match='FERNET_KEY'):
            crypto.encrypt_api_key('secret')

    def test_missing_key_raises_on_decrypt_any_value(self, monkeypatch):
        """缺 key 时读任何非空值都抛 RuntimeError（fail-closed：无法判定 legacy 明文，保守拒绝）。

        说明: 解密前需用 key 尝试解密以判定是否 legacy 明文；缺 key 时无法判定，一律抛错。
        """
        from app.config import settings

        monkeypatch.setattr(settings, 'FERNET_KEY', '')
        with pytest.raises(RuntimeError, match='FERNET_KEY'):
            crypto.decrypt_api_key('sk-legacy')


# ──────────────── 模型集成测试: Settings property ────────────────


class TestSettingsModel:
    async def test_write_is_encrypted_in_db(self, db_session, apply_key):
        """setter 写入后，DB 列值应为密文而非明文。"""
        obj = Settings(user_id='u1', api_key='sk-明文-1', cover_api_key='ck-明文', smtp_password='smtp-auth')
        db_session.add(obj)
        await db_session.commit()
        await db_session.refresh(obj)

        # 存储列是密文
        assert obj._api_key != 'sk-明文-1'  # noqa: SLF001
        assert obj._api_key.startswith('gAAAA')  # noqa: SLF001
        assert obj._cover_api_key.startswith('gAAAA')  # noqa: SLF001
        assert obj._smtp_password.startswith('gAAAA')  # noqa: SLF001

        # property 读取还原明文
        assert obj.api_key == 'sk-明文-1'
        assert obj.cover_api_key == 'ck-明文'
        assert obj.smtp_password == 'smtp-auth'

    async def test_read_legacy_plaintext(self, db_session, apply_key):
        """存量明文行（未加密）读取兼容。"""
        obj = Settings(user_id='u2')
        obj._api_key = 'sk-legacy'  # noqa: SLF001 - 模拟旧数据直接写列
        obj._cover_api_key = 'ck-legacy'  # noqa: SLF001
        obj._smtp_password = 'pw-legacy'  # noqa: SLF001
        db_session.add(obj)
        await db_session.commit()
        await db_session.refresh(obj)

        assert obj.api_key == 'sk-legacy'
        assert obj.cover_api_key == 'ck-legacy'
        assert obj.smtp_password == 'pw-legacy'

    async def test_none_assignment_ok_without_key(self, db_session, monkeypatch):
        """缺 key 时设置 None 不应抛错（清空密钥是合法操作）。"""
        from app.config import settings

        monkeypatch.setattr(settings, 'FERNET_KEY', '')
        obj = Settings(user_id='u3')
        obj.api_key = None
        obj.cover_api_key = None
        obj.smtp_password = None
        db_session.add(obj)
        await db_session.commit()
        await db_session.refresh(obj)
        assert obj.api_key is None
        assert obj.cover_api_key is None
        assert obj.smtp_password is None

    async def test_getter_raises_without_key_on_encrypted(self, db_session, apply_key, monkeypatch):
        """缺 key 时读取已加密值应抛 RuntimeError（fail-closed-on-use）。"""
        obj = Settings(user_id='u4', api_key='sk-need-key')
        db_session.add(obj)
        await db_session.commit()
        await db_session.refresh(obj)

        from app.config import settings

        monkeypatch.setattr(settings, 'FERNET_KEY', '')
        with pytest.raises(RuntimeError, match='FERNET_KEY'):
            _ = obj.api_key

    async def test_setter_raises_without_key_on_value(self, db_session, monkeypatch):
        """缺 key 时写入非空值应抛 RuntimeError（fail-closed-on-use）。"""
        from app.config import settings

        monkeypatch.setattr(settings, 'FERNET_KEY', '')
        obj = Settings(user_id='u5')
        with pytest.raises(RuntimeError, match='FERNET_KEY'):
            obj.api_key = 'sk-value'