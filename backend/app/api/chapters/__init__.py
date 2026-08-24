"""_helpers 包 — 由 _helpers.py 拆分而来，re-export 保持兼容。"""

from ._calc import _calc_seq_ratios
from ._background import _run_chapter_generation_bg
from ._mcp import _mcp_validate_context_data, _mcp_check_generation_consistency
from ._sequences import _generate_chapter_by_sequences
from ._graph import _generate_chapter_by_graph
from ._plan import merge_expansion_plan_field, parse_gen_response_blocks, _two_pass_plan

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
