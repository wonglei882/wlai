"""PM 功能配置读取模块"""

import yaml
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)

# 运行时参数覆盖缓存（自进化引擎写入，get_scanner_params 读取）
# 结构: {dimension: {key: value}}
_runtime_overrides: dict[str, dict[str, Any]] = {}


def set_runtime_overrides(overrides: dict[str, dict[str, Any]]) -> None:
    """设置运行时参数覆盖（自进化引擎每轮巡检后刷新）。"""
    global _runtime_overrides
    _runtime_overrides = {k: dict(v) for k, v in overrides.items() if v}


def clear_runtime_overrides() -> None:
    """清空运行时参数覆盖（重置/关闭自进化时调用）。"""
    global _runtime_overrides
    _runtime_overrides = {}


def get_runtime_overrides() -> dict[str, dict[str, Any]]:
    """读取当前运行时覆盖（供状态面板/调试）。"""
    return {k: dict(v) for k, v in _runtime_overrides.items()}


class PMFeatureConfig:
    """PM 功能配置管理器"""

    _instance = None
    _config: dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """加载配置文件"""
        config_path = Path(__file__).parent.parent.parent / 'config' / 'pm_features.yaml'

        if not config_path.exists():
            logger.warning(f'PM 功能配置文件不存在: {config_path}')
            self._config = self._get_default_config()
            return

        try:
            with open(config_path, encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
            logger.info('PM 功能配置加载成功')
        except Exception as e:
            logger.error(f'PM 功能配置加载失败: {e}')
            self._config = self._get_default_config()

    def _get_default_config(self) -> dict[str, Any]:
        """获取默认配置（核心功能启用，辅助功能禁用）"""
        return {
            'features': {
                'core': {'inspection': {'enabled': True}, 'repair': {'enabled': True}, 'feedback': {'enabled': True}},
                'optional': {
                    'auto_tuning': {'enabled': False},
                    'causal_graph': {'enabled': False},
                    'quality_forecast': {'enabled': False},
                    'ooc_detection': {'enabled': False},
                    'long_novel_guardian': {'enabled': False},
                    'self_evolution': {'enabled': False},
                },
                'batch': {'high_freq_words': {'enabled': True}, 'continuity_audit': {'enabled': True}},
            }
        }

    def is_enabled(self, feature_path: str) -> bool:
        """检查功能是否启用

        Args:
            feature_path: 功能路径，如 "optional.causal_graph"

        Returns:
            是否启用
        """
        keys = feature_path.split('.')
        value = self._config.get('features', {})

        for key in keys:
            if isinstance(value, dict):
                value = value.get(key, {})
            else:
                return False

        if isinstance(value, dict):
            return value.get('enabled', False)

        return bool(value)

    def get_trigger(self, feature_path: str) -> str | None:
        """获取触发条件

        Args:
            feature_path: 功能路径

        Returns:
            触发条件（on_demand/chapter_created/before_generation 等）
        """
        keys = feature_path.split('.')
        value = self._config.get('features', {})

        for key in keys:
            if isinstance(value, dict):
                value = value.get(key, {})
            else:
                return None

        if isinstance(value, dict):
            return value.get('trigger', 'on_demand')

        return 'on_demand'

    def get_feature_config(self, feature_path: str) -> dict[str, Any]:
        """获取功能完整配置

        Args:
            feature_path: 功能路径

        Returns:
            功能配置字典
        """
        keys = feature_path.split('.')
        value = self._config.get('features', {})

        for key in keys:
            if isinstance(value, dict):
                value = value.get(key, {})
            else:
                return {}

        return value if isinstance(value, dict) else {}

    def get_cost_control(self) -> dict[str, Any]:
        """获取成本控制配置"""
        return self._config.get('cost_control', {'max_tokens_per_day': 100000, 'alert_threshold': 0.8, 'auto_disable_threshold': 1.0})

    def get_performance(self) -> dict[str, Any]:
        """获取性能配置"""
        return self._config.get('performance', {'scan_timeout_seconds': 300, 'max_issues_per_round': 100, 'parallel_projects': True})

    def get_worldview_conflict_markers(self) -> dict[str, list]:
        """获取世界观冲突标记词配置。

        用于 _verify_world_keywords：检测章节正文是否引入与世界观规则冲突的设定。
        返回 {规则关键词: [冲突标记词列表]} 字典，缺失则返回默认值（兜底）。
        """
        markers = self._config.get('worldview_conflict_markers')
        if markers and isinstance(markers, dict):
            return markers
        # 兜底默认值（配置缺失时使用，保证功能可用）
        return {
            '无魔法': ['魔法', '咒语', '法术', '魔杖', '魔力'],
            '现实世界': ['穿越', '重生', '系统', '异世界', '修仙'],
            '修仙世界': ['科技', '枪械', '电脑', '手机'],
            '现代都市': ['轻功', '内力', '真气', '丹田'],
        }

    def get_comic_guardian_config(self) -> dict[str, Any]:
        """获取漫剧一致性守护配置（顶层 comic_production.guardian 段）。

        该配置位于 YAML 顶层 comic_production 下（非 features 子树），
        因此独立于 get_feature_config。缺失时返回安全默认值（守护启用+硬阻塞）。
        """
        comic = self._config.get('comic_production', {})
        if not isinstance(comic, dict):
            comic = {}
        guardian = comic.get('guardian', {})
        if not isinstance(guardian, dict):
            guardian = {}
        return {
            'enabled': guardian.get('enabled', True),
            'block_on_critical': guardian.get('block_on_critical', True),
            'visual_threshold': guardian.get('visual_threshold', 0.7),
        }

    def get_red_lines_config(self) -> dict[str, Any]:
        """获取红线系统配置（顶层 red_lines 段）。

        该配置位于 YAML 顶层 red_lines 下（非 features 子树）。
        缺失时返回安全默认值（红线引擎禁用，不改变现有行为）。
        """
        red_lines = self._config.get('red_lines')
        if not isinstance(red_lines, dict):
            return {'enabled': False, 'rules': []}
        return red_lines

    def get_scanner_params(self, dimension: str) -> dict[str, Any]:
        """获取扫描维度参数（声明式配置 + 自进化运行时覆盖）。

        Args:
            dimension: 维度标识（如 'character_consistency'）

        Returns:
            参数值字典（未配置的维度返回空 dict）
        """
        params_config = self._config.get('scanner_params', {}).get(dimension, {})
        if not isinstance(params_config, dict):
            return {}
        overrides = _runtime_overrides.get(dimension, {})
        result: dict[str, Any] = {}
        for key, spec in params_config.items():
            if not isinstance(spec, dict):
                continue
            value = spec.get('default')
            if key in overrides:
                value = overrides[key]
            result[key] = value
        return result

    def get_scanner_param_spec(self, dimension: str, key: str) -> dict[str, Any]:
        """获取单个扫描参数的完整 spec（default/min/max/description）。

        自进化引擎据此约束运行时阈值边界。
        """
        spec = self._config.get('scanner_params', {}).get(dimension, {}).get(key, {})
        return spec if isinstance(spec, dict) else {}

    def reload(self):
        """重新加载配置"""
        self._load_config()


# 全局单例
pm_feature_config = PMFeatureConfig()


# 便捷函数
def is_pm_feature_enabled(feature_path: str) -> bool:
    """检查 PM 功能是否启用"""
    return pm_feature_config.is_enabled(feature_path)


def get_pm_feature_trigger(feature_path: str) -> str | None:
    """获取 PM 功能触发条件"""
    return pm_feature_config.get_trigger(feature_path)


def get_pm_feature_config(feature_path: str) -> dict[str, Any]:
    """获取 PM 功能完整配置"""
    return pm_feature_config.get_feature_config(feature_path)


def get_scanner_params(dimension: str) -> dict[str, Any]:
    """获取扫描维度参数（含运行时覆盖）"""
    return pm_feature_config.get_scanner_params(dimension)


def get_scanner_param_spec(dimension: str, key: str) -> dict[str, Any]:
    """获取扫描参数 spec（default/min/max/description）"""
    return pm_feature_config.get_scanner_param_spec(dimension, key)
