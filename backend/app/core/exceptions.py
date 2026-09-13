"""业务异常分层 — 区分可暴露的业务错误与内部系统错误。

用法:
    raise NotFoundError('角色卡', char_id)
    raise ValidationError('episode_number 必须为正整数')
    raise AuthenticationError()
"""


class BusinessException(Exception):
    """业务异常 — 可安全暴露给用户（参数错误、资源不存在等）。"""

    def __init__(self, message: str, code: str = 'bad_request', status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(BusinessException):
    """资源不存在。"""

    def __init__(self, resource: str, resource_id: str = ''):
        detail = f'{resource}不存在' if not resource_id else f'{resource}不存在: {resource_id}'
        super().__init__(detail, 'not_found', 404)


class ValidationError(BusinessException):
    """参数校验失败。"""

    def __init__(self, message: str):
        super().__init__(message, 'validation_error', 422)


class AuthenticationError(BusinessException):
    """认证失败。"""

    def __init__(self, message: str = '未登录或认证失败'):
        super().__init__(message, 'unauthorized', 401)


class ConflictError(BusinessException):
    """资源冲突（如重复创建、状态冲突）。"""

    def __init__(self, message: str):
        super().__init__(message, 'conflict', 409)


class SystemException(Exception):
    """系统异常 — 仅记录日志，不暴露内部细节。"""

    pass
