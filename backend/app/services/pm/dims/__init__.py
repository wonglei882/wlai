"""PM 维度注册表 — 自动发现并注册所有维度文件。"""

import importlib
import pkgutil

from app.services.pm.dims.base import DimensionBase

_DIMENSION_REGISTRY: dict[str, DimensionBase] = {}


def register_dimension(dim: DimensionBase):
    """注册一个维度实例。"""
    _DIMENSION_REGISTRY[dim.name] = dim


def get_dimension(name: str) -> DimensionBase | None:
    return _DIMENSION_REGISTRY.get(name)


def get_all_dimensions() -> dict[str, DimensionBase]:
    return dict(_DIMENSION_REGISTRY)


def _auto_discover():
    """自动发现并实例化所有维度类。"""
    import app.services.pm.dims as pkg

    for _, mod_name, _ in pkgutil.iter_modules(pkg.__path__):
        if mod_name in ('base', '__init__'):
            continue
        mod = importlib.import_module(f'app.services.pm.dims.{mod_name}')
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if isinstance(attr, type) and issubclass(attr, DimensionBase) and attr is not DimensionBase:
                instance = attr()
                register_dimension(instance)


_auto_discover()
