"""VisGuard 统一异常层级与云端错误归一化。

设计意图：
- 所有 VisGuard 内部错误统一继承 VisGuardError，携带稳定 code 与 status_code，
  由 API 层统一捕获转 HTTP 响应（detail 直接透传给前端）。
- 云端供应商错误（401/402/429/5xx）通过 map_cloud_error 归一化到同一层级，
  避免把供应商原始错误码与消息裸漏给调用方。
- 重试策略按错误类型集中定义（RateLimit 指数退避 / ProviderUnavailable 线性 /
  超时固定等待），供 Phase C 云端适配落地时使用。
"""

import hashlib
import json
from dataclasses import dataclass


class VisGuardError(Exception):
    """VisGuard 错误基类。"""

    code: str = 'internal_error'
    status_code: int = 500
    detail: str = ''

    def __init__(self, detail: str = ''):
        self.detail = detail or self.detail
        super().__init__(self.detail)

    def __str__(self) -> str:
        return f'{self.code}: {self.detail}'


class VisGuardDisabledError(VisGuardError):
    """VisGuard 整体未启用（能力矩阵全部关闭）。"""

    code = 'visguard_disabled'
    status_code = 503


class BackendNotConfiguredError(VisGuardError):
    """能力后端未配置（如 generate=none 时要求生图）。"""

    code = 'backend_not_configured'
    status_code = 503


class ClipUnavailableError(VisGuardError):
    """CLIP 模型不可用（未加载 / 加载失败 / 编码失败）。"""

    code = 'clip_unavailable'
    status_code = 503


class FaissUnavailableError(VisGuardError):
    """faiss 未安装或索引操作失败。"""

    code = 'faiss_unavailable'
    status_code = 503


class InvalidImageError(VisGuardError):
    """图片无法解码 / 超过大小限制。"""

    code = 'invalid_image'
    status_code = 400


class AuthError(VisGuardError):
    """云端供应商鉴权失败。"""

    code = 'auth_error'
    status_code = 401


class RateLimitError(VisGuardError):
    """云端供应商限流。"""

    code = 'rate_limit'
    status_code = 429


class ProviderUnavailable(VisGuardError):
    """云端供应商 5xx / 服务不可达。"""

    code = 'provider_unavailable'
    status_code = 503


class QuotaExceeded(VisGuardError):
    """云端额度耗尽（402 Payment Required）。"""

    code = 'quota_exceeded'
    status_code = 402


class ProviderTimeoutError(VisGuardError):
    """云端请求超时（注意：刻意避开内置 TimeoutError 命名）。"""

    code = 'timeout'
    status_code = 504


@dataclass(frozen=True)
class RetryPolicy:
    """重试策略（供云端适配器使用）。"""

    max_retries: int
    backoff: str = 'exponential'  # exponential / linear / fixed
    base_delay: float = 1.0


RETRY_POLICIES: dict[type[VisGuardError], RetryPolicy] = {
    RateLimitError: RetryPolicy(max_retries=3, backoff='exponential', base_delay=1.0),
    ProviderUnavailable: RetryPolicy(max_retries=2, backoff='linear', base_delay=5.0),
    ProviderTimeoutError: RetryPolicy(max_retries=1, backoff='fixed', base_delay=10.0),
}


def map_cloud_error(status_code: int, body: dict) -> VisGuardError:
    """把云端供应商 HTTP 错误映射为 VisGuard 内部错误。

    Args:
        status_code: 云端 API 返回的 HTTP 状态码。
        body: 云端错误响应体（期望含 error.message / error.code）。

    Returns:
        VisGuardError: 归一化后的业务异常。
    """
    error = body.get('error', {}) if isinstance(body, dict) else {}
    message = error.get('message', '未知云端错误') if isinstance(error, dict) else str(body)
    provider_code = error.get('code', 'provider_error') if isinstance(error, dict) else ''

    if status_code == 401:
        cls = AuthError
    elif status_code == 402:
        cls = QuotaExceeded
    elif status_code == 429:
        cls = RateLimitError
    elif 500 <= status_code < 600:
        cls = ProviderUnavailable
    elif status_code == 408 or status_code == 504:
        cls = ProviderTimeoutError
    else:
        cls = VisGuardError
    exc = cls(detail=message)
    exc.code = f'{cls.code}:{provider_code}'  # 保留供应商原始错误码便于排查
    return exc


def get_idempotency_key(params: dict) -> str:
    """生成幂等键（防止生图重试重复扣费）。

    Args:
        params: 请求参数 dict。

    Returns:
        str: 规范化参数 JSON 的 sha256 前 24 位。
    """
    content = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode()).hexdigest()[:24]