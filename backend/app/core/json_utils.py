"""高性能JSON工具 — 优先用 orjson，降级到标准库

orjson 比标准 json 快 3-10 倍，中文/numpy 支持更好。
作为标准 json 的 drop-in 替换：
    from app.core import json_utils as json
    json.dumps(...) / json.loads(...) / json.JSONEncoder ...
"""

try:
    import orjson
    import json as _stdlib

    def dumps(obj, **kwargs):
        # orjson 3.11.9 不支持 OPT_ESCAPE_ASCII
        # 为保证与标准库默认行为（ensure_ascii=True 转义非ASCII）兼容，
        # ensure_ascii=True 时降级用标准库；False 时用 orjson（更快、输出UTF-8）
        """Dumps

        Args:
            obj:

        Returns:
            None
        """
        ensure_ascii = kwargs.get('ensure_ascii', True)
        if ensure_ascii:
            # 过滤掉 orjson 专有参数，避免标准库报错
            _std_kwargs = {
                k: v
                for k, v in kwargs.items()
                if k in ('skipkeys', 'ensure_ascii', 'check_circular', 'allow_nan', 'cls', 'indent', 'separators', 'default', 'sort_keys')
            }
            return _stdlib.dumps(obj, **_std_kwargs)
        option = 0
        if kwargs.get('indent') is not None:
            option |= orjson.OPT_INDENT_2
        return orjson.dumps(
            obj,
            option=option,
            default=kwargs.get('default'),
        ).decode('utf-8')

    def loads(s, **kwargs):
        return orjson.loads(s)

    # 复制标准库 json 的其余属性，保证 drop-in 兼容
    for _attr in dir(_stdlib):
        if _attr not in ('dumps', 'loads', '__name__', '__file__', '__loader__', '__spec__', '__package__', '__cached__', '__doc__'):
            globals()[_attr] = getattr(_stdlib, _attr)

    globals()['dumps'] = dumps
    globals()['loads'] = loads
    BACKEND = 'orjson'
except ImportError:
    import json as _stdlib

    globals().update(vars(_stdlib))
    BACKEND = 'stdlib'
