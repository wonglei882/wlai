"""_helpers 包 — 由 _helpers.py 拆分而来，re-export 保持兼容。

说明：独立部署时 `_calc/_background/_mcp/_sequences/_graph/_plan` 等模块
属于主系统的章节生成能力，未随本项目交付。这里做条件导入：
存在则 re-export，缺失则置为 None，保证包在任何情况下可导入。
"""

try:
    from ._calc import _calc_seq_ratios
except ImportError:
    _calc_seq_ratios = None

try:
    from ._background import _run_chapter_generation_bg
except ImportError:
    _run_chapter_generation_bg = None

try:
    from ._mcp import _mcp_validate_context_data, _mcp_check_generation_consistency
except ImportError:
    _mcp_validate_context_data = None
    _mcp_check_generation_consistency = None

try:
    from ._sequences import _generate_chapter_by_sequences
except ImportError:
    _generate_chapter_by_sequences = None

try:
    from ._graph import _generate_chapter_by_graph
except ImportError:
    _generate_chapter_by_graph = None

try:
    from ._plan import merge_expansion_plan_field, parse_gen_response_blocks, _two_pass_plan
except ImportError:
    merge_expansion_plan_field = None
    parse_gen_response_blocks = None
    _two_pass_plan = None

__all__ = [
    '_calc_seq_ratios',
    '_run_chapter_generation_bg',
    '_mcp_validate_context_data',
    '_mcp_check_generation_consistency',
    '_generate_chapter_by_sequences',
    '_generate_chapter_by_graph',
    'merge_expansion_plan_field',
    'parse_gen_response_blocks',
    '_two_pass_plan',
]
