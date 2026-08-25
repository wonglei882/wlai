#!/usr/bin/env python3
"""PM Agent 主动巡检 runner（薄壳）— 转发到统一入口 pm_inspection_runner.py。

保留本文件名以兼容既有引用（容器内 `python pm_runner.py` 或 cron pipe 进容器执行）。
原版日志写入 /app/logs/pm_inspection_YYYYMMDD.log，行为保持一致。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pm_inspection_runner import main

if __name__ == '__main__':
    main(['--log-dir', '/app/logs'])
