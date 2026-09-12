"""PM 模块专用 AIService 客户端缓存。

T0.1 优化：解决 _verify_quality_fix 中每次调用都新建 AIService 实例的问题。
每个用户维护一个缓存实例，Settings（API 配置）变更时主动失效。

实现：
- 缓存 key = (user_id, api_provider, api_key[:8], api_base_url, default_model)
- TTL 10 分钟，超时后重读 Settings 构造新实例
- 最多缓存 100 个用户（LRU）
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import logging
from app.services.ai.ai_service import AIService
from app.models.settings import Settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)

# TTL：缓存有效期（秒）
_CACHE_TTL_SECONDS = 10 * 60
# 最大缓存用户数
_MAX_CACHE_ENTRIES = 100


@dataclass
class _ClientEntry:
    client: AIService
    cached_at: float
    cache_key: tuple


_cache_lock = asyncio.Lock()
_cache: dict[str, _ClientEntry] = {}


def _cache_key_for(user_id: str, api_provider: str, api_key: str, api_base_url: str, default_model: str) -> str:
    """生成缓存 key — 用 api_key[:8] 作为指纹，避免明文存 key。"""
    key_fingerprint = (api_key or '')[:8]
    return f'{user_id}|{api_provider}|{key_fingerprint}|{api_base_url or ""}|{default_model}'


async def get_pm_ai_client(user_id: str, db: AsyncSession) -> AIService | None:
    """获取用户级 AIService 实例（带缓存）。

    Returns:
        AIService 实例，如果用户未配置 API 返回 None。
    """
    # 1) 先读缓存（asyncio.Lock，保护整个 check→update 原子段）
    now = time.time()
    async with _cache_lock:
        # 先淘汰过期项（懒清理）
        expired_keys = [k for k, v in _cache.items() if now - v.cached_at > _CACHE_TTL_SECONDS]
        for k in expired_keys:
            _cache.pop(k, None)

    # 2) 从 Settings 表读取用户配置（每次重查保证缓存 key 正确，
    #    用户改 API 配置时能重建实例。Settings 查询很轻。）
    set_r = await db.execute(select(Settings).where(Settings.user_id == user_id).limit(1))
    user_set = set_r.scalar_one_or_none()
    if not user_set or not user_set.api_key:
        return None

    provider = user_set.api_provider or 'openai'
    key = user_set.api_key
    base_url = user_set.api_base_url or ''
    model = user_set.llm_model or 'deepseek-chat'

    cache_key = _cache_key_for(user_id, provider, key, base_url, model)

    # 3) 缓存命中且未过期 — 整个「读→判→返回」在锁内完成，避免
    #    TTL 刚好过期时双写竞态。
    async with _cache_lock:
        entry = _cache.get(cache_key)
        if entry is not None and now - entry.cached_at <= _CACHE_TTL_SECONDS:
            return entry.client

        # 4) 构造新实例并写入缓存（仍在锁内 → 构造期间不会并发写入同一 key）
        client = AIService(
            user_id=user_id,
            api_provider=provider,
            api_key=key,
            api_base_url=base_url or None,
            default_model=model,
            enable_mcp=False,  # PM 质量分/评分不涉及 MCP 工具，禁用减少开销
        )

        # 超过最大条目时按 FIFO 清 20% 空间（简单够用）
        if len(_cache) >= _MAX_CACHE_ENTRIES:
            to_remove = list(_cache.keys())[: max(1, _MAX_CACHE_ENTRIES // 5)]
            for k in to_remove:
                _cache.pop(k, None)
        _cache[cache_key] = _ClientEntry(client=client, cached_at=time.time(), cache_key=tuple())

    logger.debug('[pm_ai_client] 新建 AIService 缓存 user=%s provider=%s model=%s', user_id, provider, model)
    return client


async def invalidate_pm_ai_client(user_id: str) -> None:
    # （保持与 get_pm_ai_client 同一 asyncio.Lock 语义；保留上方函数体）
    """用户 Settings 变更时主动清空该用户缓存（避免旧 key 命中）。

    调用方：Settings 变更 API（settings.py update_settings）。
    """
    async with _cache_lock:
        to_remove = [k for k in _cache if k.startswith(f'{user_id}|')]
        for k in to_remove:
            _cache.pop(k, None)
    if to_remove:
        logger.debug('[pm_ai_client] 主动清空用户 %s 的 AIService 缓存（%d 条）', user_id, len(to_remove))
