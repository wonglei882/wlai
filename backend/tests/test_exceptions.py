"""测试业务异常类与全局异常处理器。"""

import pytest
from app.core.exceptions import (
    BusinessException,
    NotFoundError,
    ValidationError,
    AuthenticationError,
    ConflictError,
    SystemException,
)


class TestBusinessException:
    """BusinessException 基类测试。"""

    def test_default_values(self):
        exc = BusinessException('测试错误')
        assert exc.message == '测试错误'
        assert exc.code == 'bad_request'
        assert exc.status_code == 400
        assert str(exc) == '测试错误'

    def test_custom_values(self):
        exc = BusinessException('自定义', code='custom_error', status_code=418)
        assert exc.code == 'custom_error'
        assert exc.status_code == 418


class TestNotFoundError:
    """NotFoundError 测试。"""

    def test_with_id(self):
        exc = NotFoundError('角色卡', 'abc123')
        assert exc.status_code == 404
        assert exc.code == 'not_found'
        assert '角色卡' in exc.message
        assert 'abc123' in exc.message

    def test_without_id(self):
        exc = NotFoundError('分镜表')
        assert exc.status_code == 404
        assert '分镜表' in exc.message
        assert ':' not in exc.message  # 没有 ID 时不显示冒号


class TestValidationError:
    """ValidationError 测试。"""

    def test_validation_error(self):
        exc = ValidationError('episode_number 必须为正整数')
        assert exc.status_code == 422
        assert exc.code == 'validation_error'
        assert '正整数' in exc.message


class TestAuthenticationError:
    """AuthenticationError 测试。"""

    def test_default_message(self):
        exc = AuthenticationError()
        assert exc.status_code == 401
        assert exc.code == 'unauthorized'
        assert '登录' in exc.message

    def test_custom_message(self):
        exc = AuthenticationError('Token 已过期')
        assert 'Token' in exc.message


class TestConflictError:
    """ConflictError 测试。"""

    def test_conflict(self):
        exc = ConflictError('角色卡已锁定')
        assert exc.status_code == 409
        assert exc.code == 'conflict'


class TestSystemException:
    """SystemException 测试。"""

    def test_system_exception(self):
        exc = SystemException('数据库连接失败')
        assert str(exc) == '数据库连接失败'
        # SystemException 不是 BusinessException 的子类
        assert not isinstance(exc, BusinessException)


class TestExceptionHierarchy:
    """异常继承关系测试。"""

    def test_business_exception_is_exception(self):
        assert issubclass(BusinessException, Exception)

    def test_not_found_is_business(self):
        assert issubclass(NotFoundError, BusinessException)

    def test_validation_is_business(self):
        assert issubclass(ValidationError, BusinessException)

    def test_auth_is_business(self):
        assert issubclass(AuthenticationError, BusinessException)

    def test_conflict_is_business(self):
        assert issubclass(ConflictError, BusinessException)

    def test_system_not_business(self):
        assert not issubclass(SystemException, BusinessException)
