"""伏笔服务辅助函数（2026-07 从 foreshadow_service.py 提炼）"""

import hashlib


def generate_stable_foreshadow_id(chapter_id: str, content: str, foreshadow_type: str = 'planted') -> str:
    """
    生成稳定的伏笔唯一标识符

    使用 chapter_id + content_hash 的方式，确保：
    1. 同一章节、相同内容的伏笔只有一个唯一ID
    2. 重新分析同一章节不会产生新ID
    3. 标识符足够短且可读

    Args:
        chapter_id: 章节ID
        content: 伏笔内容
        foreshadow_type: 伏笔类型（planted/resolved）

    Returns:
        稳定的唯一标识符，格式：{type}_{chapter_id_hash}_{content_hash}
    """
    content_normalized = content.strip().lower()
    content_hash = hashlib.md5(content_normalized.encode('utf-8')).hexdigest()[:12]  # noqa: S324
    chapter_hash = hashlib.md5(chapter_id.encode('utf-8')).hexdigest()[:8]  # noqa: S324
    return f'{foreshadow_type}_{chapter_hash}_{content_hash}'
