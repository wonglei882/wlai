#!/usr/bin/env python3
"""PM Agent 主动巡检脚本（薄壳）— 转发到统一入口 pm_inspection_runner.py。

保留本文件名以兼容既有调用（本地执行 `python run_pm_inspection.py`）。
历史版本日志写入 logs/pm_inspection.log；统一入口按天分文件 logs/pm_inspection_YYYYMMDD.log。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pm_inspection_runner import main

if __name__ == '__main__':
    main()
