"""测试夹具：确保 backend/ 根目录在 sys.path，使 app 包可导入。

用法：在 backend/ 目录下执行 `python -m pytest tests/ -v`。
"""
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
