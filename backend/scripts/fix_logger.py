"""批量替换 get_logger → logging.getLogger（保留 UTF-8 编码）。"""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), '..', 'app')
count = 0

for dirpath, dirnames, filenames in os.walk(ROOT):
    for fname in filenames:
        if not fname.endswith('.py'):
            continue
        fpath = os.path.join(dirpath, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content
        content = content.replace('from app.logger import get_logger', 'import logging')
        content = content.replace('logger = get_logger(__name__)', 'logger = logging.getLogger(__name__)')

        if content != original:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(content)
            count += 1
            print(f'Updated: {fpath}')

print(f'\nTotal files updated: {count}')
