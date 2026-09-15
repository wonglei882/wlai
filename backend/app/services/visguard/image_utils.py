"""VisGuard 图片处理工具 — 编解码 / 尺寸调整 / 指纹。

所有 VisGuard 模块共用的图片基础能力：
- PIL Image 与 base64（data URI）互转
- 按最大边长等比缩放（只缩小不放大）
- 计算图片 sha256 指纹（用于去重）

统一约定：
- API 传输使用 data URI（``data:image/png;base64,...``），与 multimodal 的
  image_url 约定衔接；``base64_to_image`` 同时兼容裸 base64 输入。
- 内部处理统一使用 RGB PIL Image（避免 RGBA/L 等模式差异）。
"""

import base64
import hashlib
import io
import logging

from PIL import Image

logger = logging.getLogger(__name__)

# 默认最大边长（超出则等比缩小）
DEFAULT_MAX_SIZE = 1024


def image_to_base64(image: Image.Image, fmt: str = 'PNG') -> str:
    """PIL Image → base64 data URI（默认 PNG）。

    Args:
        image: 输入图片（任意模式，转 RGB 后编码）。
        fmt: 输出格式（PNG / JPEG / WEBP）。

    Returns:
        str: ``data:image/png;base64,...`` 格式的 data URI。
    """
    buf = io.BytesIO()
    img = image.convert('RGB')
    img.save(buf, format=fmt)
    mime = fmt.lower().replace('jpeg', 'jpg')
    return f'data:image/{mime};base64,{base64.b64encode(buf.getvalue()).decode("ascii")}'


def base64_to_image(data: str) -> Image.Image:
    """base64 data URI 或裸 base64 → RGB PIL Image。

    Args:
        data: ``data:image/...;base64,...`` 或裸 base64 字符串。

    Returns:
        Image.Image: RGB 模式图片。

    Raises:
        ValueError: 数据无法解析为图片时抛出（含编码错误、解码失败、不可识别格式）。
    """
    try:
        payload = data
        if ',' in payload and payload.lstrip().startswith('data:'):
            payload = payload.split(',', 1)[1]
        raw = base64.b64decode(payload, validate=False)
        return bytes_to_image(raw)
    except (ValueError, TypeError) as e:
        raise ValueError(f'base64 图片数据无效: {e}') from e


def image_to_bytes(image: Image.Image, fmt: str = 'PNG') -> bytes:
    """PIL Image → 字节流（转 RGB）。"""
    buf = io.BytesIO()
    image.convert('RGB').save(buf, format=fmt)
    return buf.getvalue()


def bytes_to_image(data: bytes) -> Image.Image:
    """字节流安全打开 → RGB PIL Image。

    Raises:
        ValueError: 无法解析的图片数据（非图片 / 截断 / 损坏）。
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            # verify 触发完整解码校验（懒加载模式下损坏文件在 load 时才报错）
            img.load()
            return img.convert('RGB')
    except Exception as e:  # noqa: BLE001 - PIL 异常类型繁杂（UnidentifiedImageError/OSError/...）
        raise ValueError(f'无法解析图片数据: {e}') from e


def resize_image(image: Image.Image, max_size: int = DEFAULT_MAX_SIZE) -> Image.Image:
    """按最大边长等比缩放（只缩小不放大）。

    Args:
        image: 输入图片。
        max_size: 最大边长（像素）。

    Returns:
        Image.Image: 缩放后的 RGB 图片；原图不超过 max_size 时原样返回副本。
    """
    img = image.convert('RGB')
    if max(img.size) <= max_size:
        return img
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return img


def image_sha256(image: Image.Image) -> str:
    """图片内容指纹（基于 RGB 像素字节，忽略 PNG 元数据差异）。

    用途：参考图去重 / 缓存键。相同像素内容 → 相同指纹。
    """
    digest = hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
    return digest[:32]