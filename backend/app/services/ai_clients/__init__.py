"""AI 客户端模块

顶层不再直接导入（PEP 562 惰性 __getattr__）：避免
ai_providers → ai_clients → base_client → ai_config → ai/__init__ → ai_service
→ ai_providers 的循环导入（直接 `import app.services.ai_providers.X` 时触发）。
实际运行入口 `import app.services.ai` 不受影响。
"""

__all__ = ['BaseAIClient', 'OpenAIClient', 'AnthropicClient', 'GeminiClient']


def __getattr__(name):
    if name in ('BaseAIClient', 'OpenAIClient', 'AnthropicClient', 'GeminiClient'):
        return _lazy_import(name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def _lazy_import(name: str):
    """惰性导入单个客户端类，避免包级循环。"""
    mapping = {
        'BaseAIClient': ('app.services.ai_clients.base_client', 'BaseAIClient'),
        'OpenAIClient': ('app.services.ai_clients.openai_client', 'OpenAIClient'),
        'AnthropicClient': ('app.services.ai_clients.anthropic_client', 'AnthropicClient'),
        'GeminiClient': ('app.services.ai_clients.gemini_client', 'GeminiClient'),
    }
    if name not in mapping:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    mod_name, attr = mapping[name]
    import importlib

    mod = importlib.import_module(mod_name)
    return getattr(mod, attr)
