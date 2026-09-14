"""敏感字段加密工具（Fernet 对称加密）。

用于 settings 表中 api_key / cover_api_key / smtp_password 三个敏感列的透明加解密：

- 新写入的值一律加密存储（Fernet token 字符串）；
- 存量明文直接读取兼容（解密失败视为 legacy 明文原样返回）；
- 密钥来源于应用配置 FERNET_KEY（环境变量），缺失时读写敏感字段会抛错（fail-closed-on-use）。

说明：Fernet token 形如 ``gAAAAAB...``，长度远小于列宽 VARCHAR(500)，无需数据库迁移。
"""
from __future__ import annotations

import logging
from typing import Final

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# 进程级解密缓存：{ 密文: 明文 }，避免同一密钥值被反复解密（每行查询只解密一次）
_decrypt_cache: Final[dict[str, str]] = {}


def _get_fernet() -> Fernet:
    """从应用配置获取 FERNET_KEY 并构造 Fernet 实例；缺失时报错（fail-closed-on-use）。

    每次调用构造新实例而非缓存，避免测试过程中密钥被替换后仍命中旧实例。
    """
    from app.config import settings

    key = (settings.FERNET_KEY or '').strip()
    if not key:
        raise RuntimeError(
            'FERNET_KEY 未配置，无法加解密敏感字段（api_key / cover_api_key / smtp_password）。'
            '请在 .env 中配置 FERNET_KEY，生成方式: '
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def is_encrypted(value: str) -> bool:
    """判断给定字符串是否为有效的 Fernet token。"""
    if not value:
        return False
    try:
        _get_fernet().decrypt(value.encode())
        return True
    except (InvalidToken, RuntimeError):
        return False


def encrypt_api_key(plain: str) -> str:
    """明文 -> Fernet token 字符串。"""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_api_key(cipher: str) -> str:
    """Fernet token 字符串 -> 明文；无法解密时视为 legacy 明文原样返回。

    兼容数据库中可能存在的、尚未加密的存量明文值（InvalidToken 即视为 legacy 明文）。
    """
    if not cipher:
        return cipher
    cached = _decrypt_cache.get(cipher)
    if cached is not None:
        return cached
    try:
        plain = _get_fernet().decrypt(cipher.encode())
    except InvalidToken:
        # legacy 明文：不缓存（保持原样即可），记录一次调试日志
        logger.debug('字段值不是 Fernet token，按 legacy 明文处理')
        return cipher
    text = plain.decode()
    _decrypt_cache[cipher] = text
    return text