"""PM Agent 主动巡检 cron 脚本（薄壳）— 转发到统一入口 pm_inspection_runner.py。

保留本文件名以兼容既有 cron 调用。原版仅控制台输出，行为保持一致。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pm_inspection_runner import main

if __name__ == '__main__':
    main(['--log-dir', ''])
