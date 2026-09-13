"""测试 JSON 工具函数（safe_int / safe_float / safe_json_loads）。"""

import pytest


class TestSafeInt:
    """safe_int 测试。"""

    def test_valid_int(self):
        from app.services.json_helper import safe_int
        assert safe_int('42') == 42

    def test_invalid_returns_default(self):
        from app.services.json_helper import safe_int
        assert safe_int('not_a_number') == 0

    def test_custom_default(self):
        from app.services.json_helper import safe_int
        assert safe_int('abc', default=-1) == -1

    def test_none_returns_default(self):
        from app.services.json_helper import safe_int
        assert safe_int(None) == 0

    def test_float_string_truncates(self):
        from app.services.json_helper import safe_int
        assert safe_int('3.7') == 3


class TestSafeFloat:
    """safe_float 测试。"""

    def test_valid_float(self):
        from app.services.json_helper import safe_float
        assert safe_float('3.14') == pytest.approx(3.14)

    def test_invalid_returns_default(self):
        from app.services.json_helper import safe_float
        assert safe_float('not_a_float') == 0.0

    def test_custom_default(self):
        from app.services.json_helper import safe_float
        assert safe_float('xyz', default=1.5) == 1.5

    def test_none_returns_default(self):
        from app.services.json_helper import safe_float
        assert safe_float(None) == 0.0


class TestSafeJsonLoads:
    """safe_json_loads 测试。"""

    def test_valid_json(self):
        from app.services.json_helper import safe_json_loads
        result = safe_json_loads('{"key": "value"}')
        assert result == {'key': 'value'}

    def test_invalid_returns_none(self):
        from app.services.json_helper import safe_json_loads
        assert safe_json_loads('not json') is None

    def test_empty_string(self):
        from app.services.json_helper import safe_json_loads
        assert safe_json_loads('') is None

    def test_none_input(self):
        from app.services.json_helper import safe_json_loads
        assert safe_json_loads(None) is None

    def test_json_array(self):
        from app.services.json_helper import safe_json_loads
        result = safe_json_loads('[1, 2, 3]')
        assert result == [1, 2, 3]
